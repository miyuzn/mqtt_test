package com.example.e_textilesendingserver.provisioning

import android.bluetooth.BluetoothDevice
import android.content.Context
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.TextView
import com.example.e_textilesendingserver.R

data class BleCandidate(
    val displayName: String,
    val device: BluetoothDevice,
    val serviceUuid: String?
)

class BleDeviceAdapter(
    context: Context,
    private val items: MutableList<BleCandidate>
) : ArrayAdapter<BleCandidate>(context, 0, items) {

    override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
        val view = convertView ?: LayoutInflater.from(context)
            .inflate(R.layout.item_ble_device, parent, false)
        val entry = items[position]
        val nameView = view.findViewById<TextView>(R.id.deviceName)
        val detailView = view.findViewById<TextView>(R.id.deviceDetail)
        nameView.text = entry.displayName.ifBlank { context.getString(R.string.provision_device_unknown) }
        val builder = StringBuilder(entry.device.address)
        entry.serviceUuid?.let {
            builder.append("  ¡¤  ").append(it.take(8))
        }
        detailView.text = builder.toString()
        return view
    }
}
