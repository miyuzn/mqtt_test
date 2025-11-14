package com.example.e_textilesendingserver.provisioning

import android.Manifest
import android.app.Activity
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.bluetooth.le.ScanResult
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.text.method.TextKeyListener
import android.util.Log
import android.view.LayoutInflater
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.AutoCompleteTextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.view.isVisible
import com.example.e_textilesendingserver.R
import com.example.e_textilesendingserver.databinding.ActivityBleProvisionBinding
import com.espressif.provisioning.DeviceConnectionEvent
import com.espressif.provisioning.ESPConstants
import com.espressif.provisioning.ESPProvisionManager
import com.espressif.provisioning.WiFiAccessPoint
import com.espressif.provisioning.listeners.BleScanListener
import com.espressif.provisioning.listeners.ProvisionListener
import com.espressif.provisioning.listeners.ResponseListener
import com.espressif.provisioning.listeners.WiFiScanListener
import org.greenrobot.eventbus.EventBus
import org.greenrobot.eventbus.Subscribe
import org.greenrobot.eventbus.ThreadMode
import java.util.LinkedHashSet

/**
 * 精简版 BLE 配网界面，仅覆盖 BLE → POP → Wi-Fi → Provision 链路。
 */
class BleProvisionActivity : AppCompatActivity() {

    private lateinit var binding: ActivityBleProvisionBinding
    private lateinit var provisionManager: ESPProvisionManager
    private lateinit var bluetoothManager: BluetoothManager
    private lateinit var wifiManager: WifiManager
    private var bluetoothAdapter: BluetoothAdapter? = null

    private val handler = Handler(Looper.getMainLooper())
    private val devices = mutableListOf<BleCandidate>()
    private lateinit var deviceAdapter: BleDeviceAdapter

    private var isScanning = false
    private var isConnecting = false
    private var isConnected = false
    private var selectedIndex = -1

    private var securityLevel = SEC_TYPE_2
    private lateinit var securityType: ESPConstants.SecurityType
    private var devicePrefix: String = ProvisioningConstants.DEFAULT_DEVICE_PREFIX

    private val connectTimeout = Runnable {
        isConnecting = false
        updateProgress(false)
        showError(getString(R.string.provision_error_connect_timeout))
        provisionManager.espDevice?.disconnectDevice()
    }

    private val bleScanListener = object : BleScanListener {
        override fun scanStartFailed() {
            runOnUiThread {
                isScanning = false
                updateProgress(false)
                showError(getString(R.string.provision_error_start_scan))
            }
        }

        override fun onPeripheralFound(device: android.bluetooth.BluetoothDevice, scanResult: ScanResult) {
            val uuid = scanResult.scanRecord?.serviceUuids?.firstOrNull()?.toString()
            val name = scanResult.scanRecord?.deviceName ?: device.name ?: ""
            if (!name.isNullOrEmpty() && devicePrefix.isNotEmpty()) {
                if (!name.startsWith(devicePrefix, ignoreCase = true)) {
                    return
                }
            }
            synchronized(devices) {
                if (devices.any { it.device.address == device.address }) {
                    return
                }
                devices.add(BleCandidate(name, device, uuid))
            }
            runOnUiThread { deviceAdapter.notifyDataSetChanged() }
        }

        override fun scanCompleted() {
            runOnUiThread {
                isScanning = false
                updateProgress(false)
                if (devices.isEmpty()) {
                    binding.statusText.text = getString(R.string.provision_status_no_device)
                }
            }
        }

        override fun onFailure(e: Exception) {
            Log.e(TAG, "BLE scan failure", e)
            runOnUiThread {
                isScanning = false
                updateProgress(false)
                showError(getString(R.string.provision_error_scan_failed))
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityBleProvisionBinding.inflate(layoutInflater)
        setContentView(binding.root)

        securityLevel = intent?.getIntExtra(ProvisioningConstants.EXTRA_SECURITY_TYPE, SEC_TYPE_2)
            ?: SEC_TYPE_2
        securityType = toSecurityType(securityLevel)
        devicePrefix = intent?.getStringExtra(ProvisioningConstants.EXTRA_DEVICE_PREFIX)
            ?.takeIf { it.isNotBlank() }
            ?: ProvisioningConstants.DEFAULT_DEVICE_PREFIX

        provisionManager = ESPProvisionManager.getInstance(applicationContext)
        bluetoothManager = getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
        bluetoothAdapter = bluetoothManager.adapter
        wifiManager = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager

        if (bluetoothAdapter == null) {
            showError(getString(R.string.provision_error_ble_not_supported))
            finish()
            return
        }

        setSupportActionBar(binding.toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        supportActionBar?.title = getString(R.string.provision_title)
        binding.toolbar.setNavigationOnClickListener { finishWithCancel() }

        deviceAdapter = BleDeviceAdapter(this, devices)
        binding.deviceList.adapter = deviceAdapter
        binding.deviceList.onItemClickListener = AdapterView.OnItemClickListener { _, _, position, _ ->
            onDeviceSelected(position)
        }

        binding.scanButton.setOnClickListener { startScan(force = true) }
        updateStatus(getString(R.string.provision_status_idle))
    }

    override fun onStart() {
        super.onStart()
        EventBus.getDefault().register(this)
        ensureEspDevice()
        startScan(force = false)
    }

    override fun onStop() {
        EventBus.getDefault().unregister(this)
        stopScan()
        super.onStop()
    }

    override fun onDestroy() {
        handler.removeCallbacks(connectTimeout)
        if (isFinishing) {
            provisionManager.stopBleScan()
            provisionManager.espDevice?.disconnectDevice()
        }
        super.onDestroy()
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQUEST_ENABLE_BT) {
            if (resultCode == Activity.RESULT_OK) {
                startScan(force = true)
            } else {
                showError(getString(R.string.provision_error_bt_required))
            }
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_BLE_PERMISSIONS) {
            if (grantResults.all { it == PackageManager.PERMISSION_GRANTED }) {
                startScan(force = true)
            } else {
                showError(getString(R.string.provision_error_permissions))
            }
        }
    }

    @Subscribe(threadMode = ThreadMode.MAIN)
    fun onDeviceConnection(event: DeviceConnectionEvent) {
        when (event.eventType) {
            ESPConstants.EVENT_DEVICE_CONNECTED -> {
                handler.removeCallbacks(connectTimeout)
                isConnecting = false
                isConnected = true
                updateProgress(false)
                updateStatus(getString(R.string.provision_status_connected))
                onDeviceReady()
            }

            ESPConstants.EVENT_DEVICE_DISCONNECTED -> {
                handler.removeCallbacks(connectTimeout)
                isConnecting = false
                isConnected = false
                updateProgress(false)
                showError(getString(R.string.provision_error_disconnected))
            }

            ESPConstants.EVENT_DEVICE_CONNECTION_FAILED -> {
                handler.removeCallbacks(connectTimeout)
                isConnecting = false
                isConnected = false
                updateProgress(false)
                showError(getString(R.string.provision_error_connect_failed))
            }
        }
    }

    private fun onDeviceSelected(position: Int) {
        if (position !in devices.indices || isConnecting) return
        if (!ensureBlePrerequisites()) return
        val candidate = devices[position]
        selectedIndex = position
        isConnecting = true
        updateProgress(true)
        updateStatus(getString(R.string.provision_status_connecting, candidate.displayName.ifBlank { candidate.device.address }))
        ensureEspDevice()
        provisionManager.espDevice?.let { device ->
            device.securityType = securityType
            if (securityType == ESPConstants.SecurityType.SECURITY_2 && device.userName.isNullOrEmpty()) {
                device.userName = ProvisioningConstants.DEFAULT_SEC2_USERNAME
            }
            provisionManager.stopBleScan()
            if (hasBlePermissions()) {
                device.connectBLEDevice(candidate.device, candidate.serviceUuid)
                handler.postDelayed(connectTimeout, CONNECT_TIMEOUT_MS)
            } else {
                isConnecting = false
                updateProgress(false)
                requestBlePermissions()
            }
        }
    }

    private fun onDeviceReady() {
        val caps = provisionManager.espDevice?.deviceCapabilities ?: emptyList()
        val needsPop = securityType != ESPConstants.SecurityType.SECURITY_0 && !caps.contains(ProvisioningConstants.CAPABILITY_NO_POP)
        if (needsPop) {
            promptForPop()
        } else if (caps.contains(ProvisioningConstants.CAPABILITY_WIFI_SCAN)) {
            scanForNetworks()
        } else {
            promptManualNetwork(null)
        }
    }

    private fun promptForPop() {
        val view = LayoutInflater.from(this).inflate(R.layout.dialog_text_input, null)
        val inputLayout = view.findViewById<com.google.android.material.textfield.TextInputLayout>(R.id.inputLayout)
        val editText = view.findViewById<com.google.android.material.textfield.TextInputEditText>(R.id.inputField)
        inputLayout.hint = getString(R.string.provision_pop_hint)
        editText.inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD
        editText.setText(ProvisioningConstants.DEFAULT_POP)
        editText.setSelection(editText.text?.length ?: 0)

        com.google.android.material.dialog.MaterialAlertDialogBuilder(this)
            .setTitle(R.string.provision_dialog_pop_title)
            .setView(view)
            .setPositiveButton(R.string.provision_dialog_continue) { dialog, _ ->
                dialog.dismiss()
                val pop = editText.text?.toString().orEmpty()
                startSessionWithPop(pop)
            }
            .setNegativeButton(R.string.provision_dialog_cancel) { dialog, _ -> dialog.dismiss() }
            .setCancelable(false)
            .show()
    }

    private fun startSessionWithPop(pop: String) {
        val device = provisionManager.espDevice ?: return
        updateStatus(getString(R.string.provision_status_auth))
        updateProgress(true)
        device.proofOfPossession = pop
        device.initSession(object : ResponseListener {
            override fun onSuccess(returnData: ByteArray?) {
                runOnUiThread {
                    updateProgress(false)
                    scanForNetworks()
                }
            }

            override fun onFailure(e: Exception) {
                Log.e(TAG, "POP verification failed", e)
                runOnUiThread {
                    updateProgress(false)
                    showError(getString(R.string.provision_error_pop))
                }
            }
        })
    }

    private fun scanForNetworks() {
        val device = provisionManager.espDevice ?: return
        updateStatus(getString(R.string.provision_status_scanning_wifi))
        updateProgress(true)
        device.scanNetworks(object : WiFiScanListener {
            override fun onWifiListReceived(wifiList: ArrayList<WiFiAccessPoint>) {
                runOnUiThread {
                    updateProgress(false)
                    if (wifiList.isEmpty()) {
                        promptManualNetwork(null)
                    } else {
                        showWifiListDialog(wifiList)
                    }
                }
            }

            override fun onWiFiScanFailed(e: Exception) {
                Log.e(TAG, "Wi-Fi scan failed", e)
                runOnUiThread {
                    updateProgress(false)
                    showError(getString(R.string.provision_error_wifi_scan))
                    promptManualNetwork(null)
                }
            }
        })
    }

    private fun showWifiListDialog(wifiList: List<WiFiAccessPoint>) {
        val titles = wifiList.map {
            val rssi = if (it.rssi != 0) " (${it.rssi} dBm)" else ""
            "${it.wifiName}$rssi"
        }.toMutableList()
        titles.add(getString(R.string.provision_action_manual_network))
        com.google.android.material.dialog.MaterialAlertDialogBuilder(this)
            .setTitle(R.string.provision_dialog_wifi_title)
            .setItems(titles.toTypedArray()) { dialog, which ->
                dialog.dismiss()
                if (which == wifiList.size) {
                    promptManualNetwork(null)
                } else {
                    val ap = wifiList[which]
                    if (ap.security == ESPConstants.WIFI_OPEN.toInt()) {
                        beginProvision(ap.wifiName, "")
                    } else {
                        promptManualNetwork(ap.wifiName)
                    }
                }
            }
            .show()
    }

    private fun promptManualNetwork(presetSsid: String?) {
        val view = LayoutInflater.from(this).inflate(R.layout.dialog_wifi_credentials, null)
        val ssidInput = view.findViewById<AutoCompleteTextView>(R.id.inputSsid)
        val passInput = view.findViewById<com.google.android.material.textfield.TextInputEditText>(R.id.inputPassword)
        val savedSsids = loadPhoneWifiSsids()

        if (!presetSsid.isNullOrBlank()) {
            ssidInput.setText(presetSsid)
            ssidInput.isEnabled = false
        } else if (savedSsids.isNotEmpty()) {
            val ssidAdapter = ArrayAdapter(this, android.R.layout.simple_list_item_1, savedSsids)
            ssidInput.setAdapter(ssidAdapter)
            ssidInput.setOnClickListener { ssidInput.showDropDown() }
            ssidInput.setOnFocusChangeListener { _, hasFocus ->
                if (hasFocus) {
                    ssidInput.showDropDown()
                }
            }
            ssidInput.keyListener = null
        } else {
            ssidInput.inputType = InputType.TYPE_CLASS_TEXT
            ssidInput.keyListener = TextKeyListener.getInstance()
        }

        com.google.android.material.dialog.MaterialAlertDialogBuilder(this)
            .setTitle(R.string.provision_dialog_manual_title)
            .setView(view)
            .setPositiveButton(R.string.provision_dialog_continue) { dialog, _ ->
                dialog.dismiss()
                val ssid = ssidInput.text?.toString().orEmpty()
                val password = passInput.text?.toString().orEmpty()
                if (ssid.isBlank()) {
                    showError(getString(R.string.provision_error_ssid_required))
                } else {
                    beginProvision(ssid, password)
                }
            }
            .setNegativeButton(R.string.provision_dialog_cancel) { dialog, _ -> dialog.dismiss() }
            .show()
    }

    private fun loadPhoneWifiSsids(): List<String> {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
            != PackageManager.PERMISSION_GRANTED
        ) {
            return emptyList()
        }
        val uniqueSsids = LinkedHashSet<String>()
        runCatching {
            wifiManager.connectionInfo?.ssid?.let { ssid ->
                val clean = ssid.trim('"')
                if (clean.isNotBlank() && clean != "<unknown ssid>") {
                    uniqueSsids.add(clean)
                }
            }
            wifiManager.startScan()
            wifiManager.scanResults.forEach { result ->
                val ssid = result.SSID
                if (!ssid.isNullOrBlank()) {
                    uniqueSsids.add(ssid)
                }
            }
        }.onFailure { Log.w(TAG, "Failed to read phone Wi-Fi list", it) }
        return uniqueSsids.filter { it.isNotBlank() }
    }

    private fun beginProvision(ssid: String, password: String) {
        val device = provisionManager.espDevice ?: return
        updateStatus(getString(R.string.provision_status_provisioning, ssid))
        updateProgress(true)
        device.provision(ssid, password, object : ProvisionListener {
            override fun createSessionFailed(e: Exception) {
                handleProvisionError(e, R.string.provision_error_session)
            }

            override fun wifiConfigSent() {
                updateStatus(getString(R.string.provision_status_wifi_sent))
            }

            override fun wifiConfigFailed(e: Exception) {
                handleProvisionError(e, R.string.provision_error_wifi_send)
            }

            override fun wifiConfigApplied() {
                updateStatus(getString(R.string.provision_status_wifi_applied))
            }

            override fun wifiConfigApplyFailed(e: Exception) {
                handleProvisionError(e, R.string.provision_error_wifi_apply)
            }

            override fun provisioningFailedFromDevice(failureReason: ESPConstants.ProvisionFailureReason) {
                handleProvisionError(Exception("$failureReason"), R.string.provision_error_device)
            }

            override fun deviceProvisioningSuccess() {
                runOnUiThread {
                    updateProgress(false)
                    updateStatus(getString(R.string.provision_status_success, ssid))
                    finishWithSuccess(ssid)
                }
            }

            override fun onProvisioningFailed(e: Exception) {
                handleProvisionError(e, R.string.provision_error_generic)
            }
        })
    }

    private fun handleProvisionError(e: Exception, messageRes: Int) {
        Log.e(TAG, "Provisioning error", e)
        runOnUiThread {
            updateProgress(false)
            showError(getString(messageRes))
        }
    }

    private fun startScan(force: Boolean) {
        if (isConnecting) return
        if (!ensureBlePrerequisites()) return
        if (isScanning && !force) return
        isScanning = true
        isConnected = false
        isConnecting = false
        devices.clear()
        deviceAdapter.notifyDataSetChanged()
        updateProgress(true)
        binding.statusText.text = getString(R.string.provision_status_scanning)
        ensureEspDevice()
        provisionManager.searchBleEspDevices(devicePrefix, bleScanListener)
    }

    private fun stopScan() {
        if (!isScanning) return
        isScanning = false
        provisionManager.stopBleScan()
        updateProgress(false)
    }

    private fun ensureEspDevice() {
        val current = provisionManager.espDevice
        if (current == null) {
            provisionManager.createESPDevice(
                ESPConstants.TransportType.TRANSPORT_BLE,
                securityType
            )
        } else {
            current.securityType = securityType
        }
        provisionManager.espDevice?.let {
            if (securityType == ESPConstants.SecurityType.SECURITY_2 && it.userName.isNullOrEmpty()) {
                it.userName = ProvisioningConstants.DEFAULT_SEC2_USERNAME
            }
        }
    }

    private fun ensureBlePrerequisites(): Boolean {
        val adapter = bluetoothAdapter ?: return false
        if (!adapter.isEnabled) {
            startActivityForResult(Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE), REQUEST_ENABLE_BT)
            return false
        }
        if (!hasBlePermissions()) {
            requestBlePermissions()
            return false
        }
        return true
    }

    private fun hasBlePermissions(): Boolean {
        val permissions = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            arrayOf(
                Manifest.permission.BLUETOOTH_SCAN,
                Manifest.permission.BLUETOOTH_CONNECT,
                Manifest.permission.ACCESS_FINE_LOCATION
            )
        } else {
            arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
        }
        return permissions.all {
            ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED
        }
    }

    private fun requestBlePermissions() {
        val permissions = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            arrayOf(
                Manifest.permission.BLUETOOTH_SCAN,
                Manifest.permission.BLUETOOTH_CONNECT,
                Manifest.permission.ACCESS_FINE_LOCATION
            )
        } else {
            arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
        }
        ActivityCompat.requestPermissions(this, permissions, REQUEST_BLE_PERMISSIONS)
    }

    private fun updateProgress(active: Boolean) {
        binding.progressIndicator.isVisible = active
        binding.scanButton.isEnabled = !active
    }

    private fun updateStatus(message: String) {
        binding.statusText.text = message
    }

    private fun showError(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
        binding.statusText.text = message
    }

    private fun finishWithSuccess(ssid: String) {
        provisionManager.espDevice?.disconnectDevice()
        val intent = Intent().apply {
            putExtra(ProvisioningConstants.EXTRA_RESULT_PROVISIONED, true)
            putExtra(ProvisioningConstants.EXTRA_RESULT_SSID, ssid)
        }
        setResult(Activity.RESULT_OK, intent)
        finish()
    }

    private fun finishWithCancel() {
        val intent = Intent().apply {
            putExtra(ProvisioningConstants.EXTRA_RESULT_PROVISIONED, false)
        }
        setResult(Activity.RESULT_CANCELED, intent)
        finish()
    }

    private fun toSecurityType(value: Int): ESPConstants.SecurityType {
        return when (value) {
            SEC_TYPE_0 -> ESPConstants.SecurityType.SECURITY_0
            SEC_TYPE_1 -> ESPConstants.SecurityType.SECURITY_1
            else -> ESPConstants.SecurityType.SECURITY_2
        }
    }

    override fun onBackPressed() {
        finishWithCancel()
    }

    companion object {
        private const val TAG = "BleProvision"
        private const val REQUEST_ENABLE_BT = 1001
        private const val REQUEST_BLE_PERMISSIONS = 1002
        private const val CONNECT_TIMEOUT_MS = 20_000L

        const val SEC_TYPE_0 = 0
        const val SEC_TYPE_1 = 1
        const val SEC_TYPE_2 = 2
    }
}



