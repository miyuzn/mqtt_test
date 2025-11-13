package com.example.e_textilesendingserver.core.parser

import java.nio.ByteBuffer
import java.nio.ByteOrder

data class SensorFrame(
    val timestampSeconds: Double,
    val dn: String,
    val sn: Int,
    val pressure: IntArray,
    val magnetometer: FloatArray,
    val gyroscope: FloatArray,
    val accelerometer: FloatArray,
)

data class FrameMetadata(
    val dn: String,
    val timestampSeconds: Double?,
)

class SensorParser {

    fun peekMetadata(packet: ByteArray): FrameMetadata? {
        if (packet.size < MIN_HEADER_SIZE) return null
        if (packet[0] != START_MARKER || packet[1] != START_MARKER) return null
        val dnValue = parseDn(packet)
        val dn = String.format("%012X", dnValue and 0xFFFFFFFFFFFF)
        val ts = runCatching { parseTimestamp(packet) }.getOrNull()
        return FrameMetadata(dn = dn, timestampSeconds = ts)
    }

    fun parse(packet: ByteArray): SensorFrame? {
        if (packet.size < MIN_PACKET_SIZE) return null
        if (packet[0] != START_MARKER || packet[1] != START_MARKER) return null
        val endFirstIndex = packet.size - 2
        if (endFirstIndex < 0) return null
        if (packet[endFirstIndex] != END_MARKER || packet[endFirstIndex + 1] != END_MARKER) return null

        val dnValue = parseDn(packet)
        val dn = String.format("%012X", dnValue and 0xFFFFFFFFFFFF)
        val sn = packet[8].toUByte().toInt()
        val timestampSeconds = parseTimestamp(packet)
        val pressureStart = 15
        val pressureEnd = pressureStart + sn * 4
        val imuBytes = 36
        val expectedSize = pressureEnd + imuBytes + 2
        if (packet.size < expectedSize) return null

        val pressure = IntArray(sn)
        val buffer = ByteBuffer.wrap(packet).order(ByteOrder.LITTLE_ENDIAN)
        var offset = pressureStart
        repeat(sn) { idx ->
            pressure[idx] = buffer.getInt(offset)
            offset += 4
        }

        val magnetometer = FloatArray(3)
        repeat(3) { idx ->
            magnetometer[idx] = buffer.getFloat(pressureEnd + idx * 4)
        }
        val gyroStart = pressureEnd + 12
        val gyroscope = FloatArray(3)
        repeat(3) { idx ->
            gyroscope[idx] = buffer.getFloat(gyroStart + idx * 4)
        }
        val accStart = gyroStart + 12
        val accelerometer = FloatArray(3)
        repeat(3) { idx ->
            accelerometer[idx] = buffer.getFloat(accStart + idx * 4)
        }

        return SensorFrame(
            timestampSeconds = timestampSeconds,
            dn = dn,
            sn = sn,
            pressure = pressure,
            magnetometer = magnetometer,
            gyroscope = gyroscope,
            accelerometer = accelerometer,
        )
    }

    private fun parseTimestamp(packet: ByteArray): Double {
        val tsBuffer = ByteBuffer.wrap(packet, 9, 4).order(ByteOrder.LITTLE_ENDIAN)
        val ts = tsBuffer.int.toLong() and 0xFFFFFFFFL
        val msBuffer = ByteBuffer.wrap(packet, 13, 2).order(ByteOrder.LITTLE_ENDIAN)
        val ms = msBuffer.short.toInt() and 0xFFFF
        return ts + ms / 1000.0
    }

    private fun parseDn(packet: ByteArray): Long {
        var value = 0L
        for (i in 0 until 6) {
            val b = packet[2 + i].toLong() and 0xFF
            value = value or (b shl (i * 8))
        }
        return value
    }

    companion object {
        private const val MIN_HEADER_SIZE = 2 + 6 + 1 + 4 + 2
        private const val MIN_PACKET_SIZE = MIN_HEADER_SIZE + 36 + 2
        private val START_MARKER: Byte = 0x5A
        private val END_MARKER: Byte = 0xA5.toByte()
    }
}
