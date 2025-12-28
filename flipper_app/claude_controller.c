/**
 * Claude Controller - Flipper Zero Application
 *
 * Routes Claude Code permission requests to your Flipper for physical approval.
 * Uses BLE Serial Profile for bidirectional communication.
 *
 * Controls:
 *   Right/OK: Allow
 *   Left:     Deny
 *   Up:       Allow Always (remember)
 *   Down:     Deny Always (remember)
 *   OK Long:  Cycle permission mode
 *   Back:     Exit
 */

#include <furi.h>
#include <furi_hal.h>
#include <gui/gui.h>
#include <notification/notification.h>
#include <notification/notification_messages.h>
#include <bt/bt_service/bt.h>
#include <profiles/serial_profile.h>
#include <stdlib.h>
#include <string.h>

#define TAG "ClaudeCtrl"
#define RX_BUFFER_SIZE 256
#define MAX_DISPLAY_LINES 3


typedef struct ClaudeApp ClaudeApp;

// Forward declarations
static void bt_status_callback(BtStatus status, void* context);
static uint16_t serial_callback(SerialServiceEvent event, void* context);

struct ClaudeApp {
    Gui* gui;
    ViewPort* view_port;
    FuriMessageQueue* event_queue;
    FuriMutex* mutex;
    NotificationApp* notifications;

    Bt* bt;
    FuriHalBleProfileBase* serial_profile;
    BtStatus bt_status;

    char display_text[RX_BUFFER_SIZE];
    char last_action[32];
    bool waiting_response;
    bool muted;  // true = vibrate only, false = vibrate + sound

    uint32_t request_count;
    uint32_t allow_count;
    uint32_t deny_count;
};

static ClaudeApp* g_app = NULL;

typedef enum {
    EventTypeInput,
    EventTypeBtData,
} EventType;

typedef struct {
    EventType type;
    InputEvent input;
} AppEvent;

// Send data over BLE
static void bt_send(ClaudeApp* app, const char* data) {
    if(app->serial_profile) {
        ble_profile_serial_tx(app->serial_profile, (uint8_t*)data, strlen(data));
        FURI_LOG_I(TAG, "TX: %s", data);
    }
}

// BLE Serial callback - receives data from host
static uint16_t serial_callback(SerialServiceEvent event, void* context) {
    UNUSED(context);

    if(event.event == SerialServiceEventTypeDataReceived) {
        FURI_LOG_I(TAG, "RX %u bytes", event.data.size);

        if(g_app && event.data.size > 0) {
            // Check if this is a DONE message (tool completed, clear pending request)
            if(event.data.size >= 4 && strncmp((char*)event.data.buffer, "DONE", 4) == 0) {
                furi_mutex_acquire(g_app->mutex, FuriWaitForever);
                if(g_app->waiting_response) {
                    // User handled it via Claude UI, not Flipper
                    strcpy(g_app->last_action, "(via Claude)");
                    g_app->waiting_response = false;
                }
                furi_mutex_release(g_app->mutex);

                // Queue UI update
                AppEvent evt = {.type = EventTypeBtData};
                furi_message_queue_put(g_app->event_queue, &evt, 0);
                return 0;
            }

            // Acknowledge receipt of permission request
            ble_profile_serial_tx(g_app->serial_profile, (uint8_t*)"ACK\n", 4);

            furi_mutex_acquire(g_app->mutex, FuriWaitForever);

            size_t len = event.data.size;
            if(len >= RX_BUFFER_SIZE) len = RX_BUFFER_SIZE - 1;

            memcpy(g_app->display_text, event.data.buffer, len);
            g_app->display_text[len] = '\0';

            // Strip newlines for display
            for(size_t i = 0; i < len; i++) {
                if(g_app->display_text[i] == '\n' || g_app->display_text[i] == '\r') {
                    g_app->display_text[i] = ' ';
                }
            }

            g_app->waiting_response = true;
            g_app->request_count++;
            g_app->last_action[0] = '\0';

            furi_mutex_release(g_app->mutex);

            // Notify user (vibrate only if muted, beep+vibrate if not)
            if(g_app->muted) {
                notification_message(g_app->notifications, &sequence_single_vibro);
            } else {
                notification_message(g_app->notifications, &sequence_success);
            }

            // Queue UI update
            AppEvent evt = {.type = EventTypeBtData};
            furi_message_queue_put(g_app->event_queue, &evt, 0);
        }
    }
    return 0;
}

// Called when BT status changes
static void bt_status_callback(BtStatus status, void* context) {
    ClaudeApp* app = context;
    FURI_LOG_I(TAG, "BT status: %d", status);

    furi_mutex_acquire(app->mutex, FuriWaitForever);
    app->bt_status = status;
    furi_mutex_release(app->mutex);

    if(status == BtStatusConnected && app->serial_profile) {
        // Re-set our callback after BT service sets theirs
        FURI_LOG_I(TAG, "Connection detected, setting callback...");
        furi_delay_ms(100);
        ble_profile_serial_set_event_callback(app->serial_profile, 128, serial_callback, app);
        // Don't beep on connect - we'll beep on first request
    } else if(status == BtStatusAdvertising) {
        // Waiting for connection
        furi_mutex_acquire(app->mutex, FuriWaitForever);
        strcpy(app->display_text, "Waiting for connection...");
        furi_mutex_release(app->mutex);
    }
}

// Draw the UI
static void draw_callback(Canvas* canvas, void* ctx) {
    ClaudeApp* app = ctx;
    furi_mutex_acquire(app->mutex, FuriWaitForever);

    canvas_clear(canvas);
    canvas_set_color(canvas, ColorBlack);

    // Header bar
    canvas_set_font(canvas, FontPrimary);
    canvas_draw_str(canvas, 2, 10, "Claude Controller");

    // Connection indicator
    canvas_set_font(canvas, FontSecondary);
    const char* conn_str;
    switch(app->bt_status) {
        case BtStatusConnected: conn_str = "[*]"; break;
        case BtStatusAdvertising: conn_str = "[.]"; break;
        default: conn_str = "[-]"; break;
    }
    canvas_draw_str(canvas, 110, 10, conn_str);

    canvas_draw_line(canvas, 0, 12, 128, 12);

    // Status line (mute indicator + stats)
    if(app->muted) {
        canvas_draw_str(canvas, 2, 22, "[MUTE]");
    }

    // Stats
    char stats[32];
    snprintf(stats, sizeof(stats), "%lu/%lu/%lu",
        app->request_count, app->allow_count, app->deny_count);
    canvas_draw_str(canvas, 90, 22, stats);

    canvas_draw_line(canvas, 0, 24, 128, 24);

    // Main content area
    if(app->waiting_response) {
        // Show permission request with word wrap
        canvas_set_font(canvas, FontSecondary);

        const char* text = app->display_text;
        size_t len = strlen(text);
        int y = 34;
        size_t pos = 0;

        while(pos < len && y < 50) {
            // Find how much fits on one line (~21 chars)
            size_t line_len = len - pos;
            if(line_len > 21) line_len = 21;

            char line[24];
            strncpy(line, text + pos, line_len);
            line[line_len] = '\0';

            canvas_draw_str(canvas, 2, y, line);
            y += 10;
            pos += line_len;
        }

        // Button hints: No, Always, Yes
        canvas_draw_line(canvas, 0, 52, 128, 52);
        canvas_set_font(canvas, FontSecondary);
        canvas_draw_str(canvas, 4, 62, "< No");
        canvas_draw_str_aligned(canvas, 64, 62, AlignCenter, AlignBottom, "^ Always");
        canvas_draw_str_aligned(canvas, 124, 62, AlignRight, AlignBottom, "Yes >");

    } else {
        // Idle state
        canvas_set_font(canvas, FontSecondary);

        if(app->last_action[0] != '\0') {
            canvas_draw_str_aligned(canvas, 64, 36, AlignCenter, AlignCenter, app->last_action);
        } else if(app->bt_status == BtStatusConnected) {
            canvas_draw_str_aligned(canvas, 64, 36, AlignCenter, AlignCenter, "Ready - awaiting requests");
        } else {
            canvas_draw_str_aligned(canvas, 64, 36, AlignCenter, AlignCenter, app->display_text);
        }

        // Hint
        canvas_draw_str_aligned(canvas, 64, 58, AlignCenter, AlignCenter, "Hold Down: mute");
    }

    furi_mutex_release(app->mutex);
}

static void input_callback(InputEvent* input_event, void* ctx) {
    ClaudeApp* app = ctx;
    AppEvent event = {.type = EventTypeInput, .input = *input_event};
    furi_message_queue_put(app->event_queue, &event, 0);
}

int32_t claude_controller_app(void* p) {
    UNUSED(p);

    ClaudeApp* app = malloc(sizeof(ClaudeApp));
    memset(app, 0, sizeof(ClaudeApp));
    g_app = app;

    app->mutex = furi_mutex_alloc(FuriMutexTypeNormal);
    app->event_queue = furi_message_queue_alloc(8, sizeof(AppEvent));
    app->bt_status = BtStatusOff;

    app->view_port = view_port_alloc();
    view_port_draw_callback_set(app->view_port, draw_callback, app);
    view_port_input_callback_set(app->view_port, input_callback, app);

    app->gui = furi_record_open(RECORD_GUI);
    gui_add_view_port(app->gui, app->view_port, GuiLayerFullscreen);

    app->notifications = furi_record_open(RECORD_NOTIFICATION);
    app->bt = furi_record_open(RECORD_BT);

    // Register for BT status changes
    bt_set_status_changed_callback(app->bt, bt_status_callback, app);

    // Start serial profile
    FURI_LOG_I(TAG, "Starting serial profile...");
    app->serial_profile = bt_profile_start(app->bt, ble_profile_serial, NULL);

    if(app->serial_profile) {
        ble_profile_serial_set_event_callback(app->serial_profile, 128, serial_callback, app);
        strcpy(app->display_text, "BLE ready - connect host");
        FURI_LOG_I(TAG, "Serial profile started");
    } else {
        strcpy(app->display_text, "BLE init failed!");
        FURI_LOG_E(TAG, "Failed to start serial profile");
    }

    AppEvent event;
    bool running = true;

    while(running) {
        FuriStatus status = furi_message_queue_get(app->event_queue, &event, 100);

        if(status == FuriStatusOk && event.type == EventTypeInput) {
            InputEvent* input = &event.input;

            // Long press Down = toggle mute
            if(input->key == InputKeyDown && input->type == InputTypeLong) {
                furi_mutex_acquire(app->mutex, FuriWaitForever);
                app->muted = !app->muted;
                snprintf(app->last_action, sizeof(app->last_action),
                    app->muted ? "Sound OFF" : "Sound ON");
                furi_mutex_release(app->mutex);

                notification_message(app->notifications, &sequence_single_vibro);
            }
            // Short presses
            else if(input->type == InputTypeShort) {
                switch(input->key) {
                case InputKeyBack:
                    running = false;
                    break;

                case InputKeyOk:
                case InputKeyRight:
                    // Allow
                    if(app->waiting_response) {
                        bt_send(app, "Y\n");
                        furi_mutex_acquire(app->mutex, FuriWaitForever);
                        strcpy(app->last_action, "ALLOWED");
                        app->waiting_response = false;
                        app->allow_count++;
                        furi_mutex_release(app->mutex);
                    }
                    break;

                case InputKeyLeft:
                    // Deny
                    if(app->waiting_response) {
                        bt_send(app, "N\n");
                        furi_mutex_acquire(app->mutex, FuriWaitForever);
                        strcpy(app->last_action, "DENIED");
                        app->waiting_response = false;
                        app->deny_count++;
                        furi_mutex_release(app->mutex);
                    }
                    break;

                case InputKeyUp:
                    // Allow Always (remember)
                    if(app->waiting_response) {
                        bt_send(app, "A\n");  // A = Allow always
                        furi_mutex_acquire(app->mutex, FuriWaitForever);
                        strcpy(app->last_action, "ALWAYS ALLOW");
                        app->waiting_response = false;
                        app->allow_count++;
                        furi_mutex_release(app->mutex);
                    }
                    break;

                case InputKeyDown:
                    // Deny Always (never allow)
                    if(app->waiting_response) {
                        bt_send(app, "D\n");  // D = Deny always
                        furi_mutex_acquire(app->mutex, FuriWaitForever);
                        strcpy(app->last_action, "NEVER ALLOW");
                        app->waiting_response = false;
                        app->deny_count++;
                        furi_mutex_release(app->mutex);
                    }
                    break;

                default:
                    break;
                }
            }
        }

        view_port_update(app->view_port);
    }

    FURI_LOG_I(TAG, "Stopping...");

    bt_set_status_changed_callback(app->bt, NULL, NULL);

    if(app->serial_profile) {
        bt_profile_restore_default(app->bt);
    }

    gui_remove_view_port(app->gui, app->view_port);
    view_port_free(app->view_port);

    furi_record_close(RECORD_GUI);
    furi_record_close(RECORD_NOTIFICATION);
    furi_record_close(RECORD_BT);

    furi_mutex_free(app->mutex);
    furi_message_queue_free(app->event_queue);

    g_app = NULL;
    free(app);

    return 0;
}
