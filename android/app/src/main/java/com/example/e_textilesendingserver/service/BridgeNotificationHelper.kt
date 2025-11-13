package com.example.e_textilesendingserver.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import com.example.e_textilesendingserver.MainActivity
import com.example.e_textilesendingserver.R

class BridgeNotificationHelper(private val context: Context) {

    private val notificationManager =
        context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

    fun ensureChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                context.getString(R.string.app_name),
                NotificationManager.IMPORTANCE_LOW
            )
            notificationManager.createNotificationChannel(channel)
        }
    }

    fun build(state: BridgeState): Notification {
        val pendingIntent = PendingIntent.getActivity(
            context,
            0,
            Intent(context, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val contentText = when (state) {
            is BridgeState.Running -> {
                val metrics = state.metrics
                "UDP ${metrics.packetsIn} / MQTT ${metrics.parsedPublished} / 设备 ${metrics.deviceCount}"
            }
            is BridgeState.Error -> "错误: ${state.message}"
            BridgeState.Starting -> "正在连接 MQTT / UDP"
            BridgeState.Idle -> "已停止"
        }
        return NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(context.getString(R.string.app_name))
            .setContentText(contentText)
            .setStyle(NotificationCompat.BigTextStyle().bigText(contentText))
            .setContentIntent(pendingIntent)
            .setOngoing(state is BridgeState.Running || state is BridgeState.Starting)
            .build()
    }

    companion object {
        const val CHANNEL_ID = "bridge-channel"
        const val NOTIFICATION_ID = 1001
    }
}
