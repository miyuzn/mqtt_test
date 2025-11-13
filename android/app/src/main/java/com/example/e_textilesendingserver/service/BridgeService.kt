package com.example.e_textilesendingserver.service

import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import androidx.lifecycle.LifecycleService
import androidx.lifecycle.lifecycleScope
import com.example.e_textilesendingserver.core.config.BridgeConfigRepository
import kotlinx.coroutines.launch

class BridgeService : LifecycleService() {

    private lateinit var controller: BridgeController
    private lateinit var notificationHelper: BridgeNotificationHelper
    private lateinit var notificationManager: NotificationManager

    override fun onCreate() {
        super.onCreate()
        val repository = BridgeConfigRepository(applicationContext)
        controller = BridgeController(repository)
        notificationHelper = BridgeNotificationHelper(this)
        notificationHelper.ensureChannel()
        notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        lifecycleScope.launch {
            BridgeStatusStore.state.collect { state ->
                notificationManager.notify(
                    BridgeNotificationHelper.NOTIFICATION_ID,
                    notificationHelper.build(state)
                )
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val initialNotification = notificationHelper.build(BridgeStatusStore.state.value)
        startForeground(BridgeNotificationHelper.NOTIFICATION_ID, initialNotification)
        controller.start()
        return START_STICKY
    }

    override fun onDestroy() {
        controller.stop()
        notificationManager.cancel(BridgeNotificationHelper.NOTIFICATION_ID)
        super.onDestroy()
    }
}
