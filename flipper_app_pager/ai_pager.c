/**
 * AI Pager - Flipper Zero Application
 *
 * Receives notifications from Claude/AI via BLE and displays them.
 * Simpler than Claude Controller - just display + vibrate + dismiss.
 *
 * Protocol:
 *   PAGE:<pattern>:<auto>:<message>\n
 *   VIBRATE:<pattern>\n
 *
 * Patterns: short, long, urgent, silent
 * Auto: 0 = wait for OK, 1 = auto-dismiss after 5s
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

#define TAG "AIPager"
#define RX_BUFFER_SIZE 128
#define AUTO_DISMISS_MS 5000

typedef struct AIPagerApp AIPagerApp;

static void bt_status_callback(BtStatus status, void* context);
static uint16_t serial_callback(SerialServiceEvent event, void* context);

struct AIPagerApp {
    Gui* gui;
    ViewPort* view_port;
    FuriMessageQueue* event_queue;
    FuriMutex* mutex;
    NotificationApp* notifications;

    Bt* bt;
    FuriHalBleProfileBase* serial_profile;
    BtStatus bt_status;

    char message[RX_BUFFER_SIZE];
    bool has_message;
    bool auto_dismiss;
    uint32_t message_time;
};

static AIPagerApp* g_app = NULL;

typedef enum {
    EventTypeInput,
    EventTypeBtData,
    EventTypeTick,
} EventType;

typedef struct {
    EventType type;
    InputEvent input;
} AppEvent;

// Notification sequences for different patterns
static const NotificationSequence sequence_vibro_long = {
    &message_vibro_on,
    &message_delay_500,
    &message_vibro_off,
    NULL,
};

static const NotificationSequence sequence_vibro_urgent = {
    &message_vibro_on,
    &message_delay_100,
    &message_vibro_off,
    &message_delay_100,
    &message_vibro_on,
    &message_delay_100,
    &message_vibro_off,
    &message_delay_100,
    &message_vibro_on,
    &message_delay_100,
    &message_vibro_off,
    NULL,
};

static void do_vibrate(AIPagerApp* app, const char* pattern) {
    if(strcmp(pattern, "silent") == 0) {
        // No vibration
    } else if(strcmp(pattern, "long") == 0) {
        notification_message(app->notifications, &sequence_vibro_long);
    } else if(strcmp(pattern, "urgent") == 0) {
        notification_message(app->notifications, &sequence_vibro_urgent);
    } else {
        // Default: short
        notification_message(app->notifications, &sequence_single_vibro);
    }
}

// Parse incoming message: PAGE:<pattern>:<auto>:<message> or VIBRATE:<pattern>
static void handle_message(AIPagerApp* app, const char* data, size_t len) {
    char buf[RX_BUFFER_SIZE];
    if(len >= RX_BUFFER_SIZE) len = RX_BUFFER_SIZE - 1;
    memcpy(buf, data, len);
    buf[len] = '\0';

    // Strip newlines
    for(size_t i = 0; i < len; i++) {
        if(buf[i] == '\n' || buf[i] == '\r') buf[i] = '\0';
    }

    if(strncmp(buf, "PAGE:", 5) == 0) {
        // Parse: PAGE:<pattern>:<auto>:<message>
        char* ptr = buf + 5;
        char* pattern = ptr;
        char* auto_str = NULL;
        char* message = NULL;

        // Find first colon (end of pattern)
        char* colon1 = strchr(ptr, ':');
        if(colon1) {
            *colon1 = '\0';
            auto_str = colon1 + 1;
            // Find second colon (end of auto)
            char* colon2 = strchr(auto_str, ':');
            if(colon2) {
                *colon2 = '\0';
                message = colon2 + 1;
            }
        }

        if(message) {
            furi_mutex_acquire(app->mutex, FuriWaitForever);
            strncpy(app->message, message, RX_BUFFER_SIZE - 1);
            app->message[RX_BUFFER_SIZE - 1] = '\0';
            app->has_message = true;
            app->auto_dismiss = (auto_str && auto_str[0] == '1');
            app->message_time = furi_get_tick();
            furi_mutex_release(app->mutex);

            do_vibrate(app, pattern);
        }
    } else if(strncmp(buf, "VIBRATE:", 8) == 0) {
        // Just vibrate, no message
        do_vibrate(app, buf + 8);
    }

    // Queue UI update
    AppEvent evt = {.type = EventTypeBtData};
    furi_message_queue_put(app->event_queue, &evt, 0);
}

static uint16_t serial_callback(SerialServiceEvent event, void* context) {
    UNUSED(context);

    if(event.event == SerialServiceEventTypeDataReceived) {
        FURI_LOG_I(TAG, "RX %u bytes", event.data.size);

        if(g_app && event.data.size > 0) {
            // Send ACK
            ble_profile_serial_tx(g_app->serial_profile, (uint8_t*)"ACK\n", 4);
            handle_message(g_app, (char*)event.data.buffer, event.data.size);
        }
    }
    return 0;
}

static void bt_status_callback(BtStatus status, void* context) {
    AIPagerApp* app = context;
    FURI_LOG_I(TAG, "BT status: %d", status);

    furi_mutex_acquire(app->mutex, FuriWaitForever);
    app->bt_status = status;
    furi_mutex_release(app->mutex);

    if(status == BtStatusConnected && app->serial_profile) {
        furi_delay_ms(100);
        ble_profile_serial_set_event_callback(app->serial_profile, 128, serial_callback, app);
    }
}

static void draw_callback(Canvas* canvas, void* ctx) {
    AIPagerApp* app = ctx;
    furi_mutex_acquire(app->mutex, FuriWaitForever);

    canvas_clear(canvas);
    canvas_set_color(canvas, ColorBlack);

    // Header
    canvas_set_font(canvas, FontPrimary);
    canvas_draw_str(canvas, 2, 10, "AI Pager");

    // Connection indicator
    canvas_set_font(canvas, FontSecondary);
    const char* conn = app->bt_status == BtStatusConnected ? "[*]" :
                       app->bt_status == BtStatusAdvertising ? "[.]" : "[-]";
    canvas_draw_str(canvas, 110, 10, conn);

    canvas_draw_line(canvas, 0, 12, 128, 12);

    // Message area
    if(app->has_message) {
        canvas_set_font(canvas, FontSecondary);

        // Word wrap - 2 lines max
        const char* text = app->message;
        size_t len = strlen(text);
        int y = 28;

        for(int line = 0; line < 2 && text[0]; line++) {
            size_t line_len = len > 21 ? 21 : len;
            char buf[24];
            strncpy(buf, text, line_len);
            buf[line_len] = '\0';
            canvas_draw_str(canvas, 2, y, buf);
            y += 12;
            text += line_len;
            len -= line_len;
        }

        // Dismiss hint
        canvas_draw_line(canvas, 0, 52, 128, 52);
        if(app->auto_dismiss) {
            canvas_draw_str_aligned(canvas, 64, 62, AlignCenter, AlignBottom, "(auto-dismiss)");
        } else {
            canvas_draw_str_aligned(canvas, 64, 62, AlignCenter, AlignBottom, "Press OK to dismiss");
        }
    } else {
        canvas_set_font(canvas, FontSecondary);
        canvas_draw_str_aligned(canvas, 64, 32, AlignCenter, AlignCenter, "Waiting for messages...");
        canvas_draw_str_aligned(canvas, 64, 48, AlignCenter, AlignCenter, "Press Back to exit");
    }

    furi_mutex_release(app->mutex);
}

static void input_callback(InputEvent* input_event, void* ctx) {
    AIPagerApp* app = ctx;
    AppEvent event = {.type = EventTypeInput, .input = *input_event};
    furi_message_queue_put(app->event_queue, &event, 0);
}

int32_t ai_pager_app(void* p) {
    UNUSED(p);

    AIPagerApp* app = malloc(sizeof(AIPagerApp));
    memset(app, 0, sizeof(AIPagerApp));
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

    bt_set_status_changed_callback(app->bt, bt_status_callback, app);

    FURI_LOG_I(TAG, "Starting serial profile...");
    app->serial_profile = bt_profile_start(app->bt, ble_profile_serial, NULL);

    if(app->serial_profile) {
        ble_profile_serial_set_event_callback(app->serial_profile, 128, serial_callback, app);
        FURI_LOG_I(TAG, "BLE ready");
    } else {
        FURI_LOG_E(TAG, "BLE init failed");
    }

    AppEvent event;
    bool running = true;

    while(running) {
        FuriStatus status = furi_message_queue_get(app->event_queue, &event, 100);

        // Check auto-dismiss
        if(app->has_message && app->auto_dismiss) {
            uint32_t elapsed = furi_get_tick() - app->message_time;
            if(elapsed >= furi_ms_to_ticks(AUTO_DISMISS_MS)) {
                furi_mutex_acquire(app->mutex, FuriWaitForever);
                app->has_message = false;
                app->message[0] = '\0';
                furi_mutex_release(app->mutex);
            }
        }

        if(status == FuriStatusOk && event.type == EventTypeInput) {
            if(event.input.type == InputTypeShort) {
                switch(event.input.key) {
                case InputKeyBack:
                    running = false;
                    break;

                case InputKeyOk:
                case InputKeyRight:
                    // Dismiss message
                    if(app->has_message) {
                        furi_mutex_acquire(app->mutex, FuriWaitForever);
                        app->has_message = false;
                        app->message[0] = '\0';
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
