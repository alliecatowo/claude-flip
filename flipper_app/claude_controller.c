/**
 * Claude Controller - Flipper Zero Application
 * Uses BLE Serial Profile for bidirectional communication.
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

typedef struct ClaudeApp ClaudeApp;

// Forward declare callback
static void bt_status_callback(BtStatus status, void* context);

struct ClaudeApp {
    Gui* gui;
    ViewPort* view_port;
    FuriMessageQueue* event_queue;
    FuriMutex* mutex;
    NotificationApp* notifications;

    Bt* bt;
    FuriHalBleProfileBase* serial_profile;

    char display_text[RX_BUFFER_SIZE];
    char response[64];
    bool waiting_response;
    bool callback_set;
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

// BLE Serial callback
static uint16_t serial_callback(SerialServiceEvent event, void* context) {
    UNUSED(context);

    if(event.event == SerialServiceEventTypeDataReceived) {
        FURI_LOG_I(TAG, "RX %u bytes", event.data.size);

        if(g_app && event.data.size > 0) {
            // Immediately echo back to confirm receipt
            ble_profile_serial_tx(g_app->serial_profile, (uint8_t*)"ACK\n", 4);
            FURI_LOG_I(TAG, "Sent ACK");

            furi_mutex_acquire(g_app->mutex, FuriWaitForever);

            size_t len = event.data.size;
            if(len >= RX_BUFFER_SIZE) len = RX_BUFFER_SIZE - 1;

            memcpy(g_app->display_text, event.data.buffer, len);
            g_app->display_text[len] = '\0';

            // Strip newlines
            for(size_t i = 0; i < len; i++) {
                if(g_app->display_text[i] == '\n' || g_app->display_text[i] == '\r') {
                    g_app->display_text[i] = ' ';
                }
            }

            g_app->waiting_response = true;
            furi_mutex_release(g_app->mutex);

            notification_message(g_app->notifications, &sequence_single_vibro);

            AppEvent evt = {.type = EventTypeBtData};
            furi_message_queue_put(g_app->event_queue, &evt, 0);
        }
    }
    return 0;
}

// Called when BT status changes - re-set our callback after connection
static void bt_status_callback(BtStatus status, void* context) {
    ClaudeApp* app = context;
    FURI_LOG_I(TAG, "BT status: %d", status);

    if(status == BtStatusConnected && app->serial_profile) {
        // BT service just set its callback, override it with ours
        FURI_LOG_I(TAG, "Connection detected, re-setting callback...");
        furi_delay_ms(100); // Small delay to let BT service finish
        ble_profile_serial_set_event_callback(app->serial_profile, 128, serial_callback, app);
        FURI_LOG_I(TAG, "Callback re-set!");
        app->callback_set = true;
    }
}

static void draw_callback(Canvas* canvas, void* ctx) {
    ClaudeApp* app = ctx;
    furi_mutex_acquire(app->mutex, FuriWaitForever);

    canvas_clear(canvas);
    canvas_set_color(canvas, ColorBlack);

    canvas_set_font(canvas, FontPrimary);
    canvas_draw_str(canvas, 2, 12, "Claude Controller");
    canvas_draw_line(canvas, 0, 14, 128, 14);

    canvas_set_font(canvas, FontSecondary);
    canvas_draw_str(canvas, 90, 12, app->serial_profile ? "[BT]" : "[--]");

    if(app->display_text[0] != '\0') {
        canvas_draw_str(canvas, 2, 28, app->display_text);
    } else {
        canvas_draw_str_aligned(canvas, 64, 32, AlignCenter, AlignCenter, "Waiting...");
    }

    if(app->waiting_response) {
        canvas_draw_line(canvas, 0, 52, 128, 52);
        canvas_draw_str(canvas, 4, 62, "<N");
        canvas_draw_str_aligned(canvas, 64, 62, AlignCenter, AlignBottom, "OK:Y");
        canvas_draw_str_aligned(canvas, 124, 62, AlignRight, AlignBottom, "Y>");
    } else if(app->response[0] != '\0') {
        canvas_draw_str_aligned(canvas, 64, 58, AlignCenter, AlignCenter, app->response);
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

    app->view_port = view_port_alloc();
    view_port_draw_callback_set(app->view_port, draw_callback, app);
    view_port_input_callback_set(app->view_port, input_callback, app);

    app->gui = furi_record_open(RECORD_GUI);
    gui_add_view_port(app->gui, app->view_port, GuiLayerFullscreen);

    app->notifications = furi_record_open(RECORD_NOTIFICATION);
    app->bt = furi_record_open(RECORD_BT);

    // Register for BT status changes to re-set callback after connection
    bt_set_status_changed_callback(app->bt, bt_status_callback, app);

    // Start serial profile
    FURI_LOG_I(TAG, "Starting serial profile...");
    app->serial_profile = bt_profile_start(app->bt, ble_profile_serial, NULL);
    FURI_LOG_I(TAG, "bt_profile_start returned: %p", app->serial_profile);

    if(app->serial_profile) {
        FURI_LOG_I(TAG, "Setting callback...");
        ble_profile_serial_set_event_callback(app->serial_profile, 128, serial_callback, app);
        FURI_LOG_I(TAG, "Callback set!");
        strcpy(app->display_text, "BLE Serial ready!");
    } else {
        strcpy(app->display_text, "BLE init failed!");
        FURI_LOG_E(TAG, "Failed to start serial profile");
    }

    AppEvent event;
    bool running = true;

    while(running) {
        FuriStatus status = furi_message_queue_get(app->event_queue, &event, 100);

        if(status == FuriStatusOk) {
            if(event.type == EventTypeInput && event.input.type == InputTypeShort) {
                switch(event.input.key) {
                case InputKeyBack:
                    running = false;
                    break;
                case InputKeyOk:
                    if(app->waiting_response) {
                        bt_send(app, "Y\n");
                        furi_mutex_acquire(app->mutex, FuriWaitForever);
                        strcpy(app->response, "-> ALLOWED");
                        app->waiting_response = false;
                        furi_mutex_release(app->mutex);
                    } else {
                        // Test: send PING when idle
                        bt_send(app, "PING\n");
                        furi_mutex_acquire(app->mutex, FuriWaitForever);
                        strcpy(app->response, "Sent PING");
                        furi_mutex_release(app->mutex);
                    }
                    break;
                case InputKeyRight:
                    if(app->waiting_response) {
                        bt_send(app, "Y\n");
                        furi_mutex_acquire(app->mutex, FuriWaitForever);
                        strcpy(app->response, "-> ALLOWED");
                        app->waiting_response = false;
                        furi_mutex_release(app->mutex);
                    }
                    break;
                case InputKeyLeft:
                    if(app->waiting_response) {
                        bt_send(app, "N\n");
                        furi_mutex_acquire(app->mutex, FuriWaitForever);
                        strcpy(app->response, "-> DENIED");
                        app->waiting_response = false;
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
