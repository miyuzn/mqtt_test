
import re

def update_html(content):
    # 1. Add COP toggle and update Dual Mode text
    # 查找 controls 区域
    controls_pattern = r'(<div class="form-check form-switch dual-mode-switch mb-0">.*?<label.*?data-i18n="controls.dual_mode">)(.*?)(</label>.*?</div>)'
    
    def controls_repl(match):
        prefix = match.group(1)
        # old_label = match.group(2) # "双设备模式"
        suffix = match.group(3)
        
        # 构建新的 controls HTML
        new_html = """<div class="d-flex flex-wrap gap-3">
                <div class="form-check form-switch mb-0">
                  <input class="form-check-input" type="checkbox" id="multi-mode-toggle" />
                  <label class="form-check-label" for="multi-mode-toggle" data-i18n="controls.multi_mode">多设备模式</label>
                </div>
                <div class="form-check form-switch mb-0">
                  <input class="form-check-input" type="checkbox" id="cop-visibility-toggle" checked />
                  <label class="form-check-label" for="cop-visibility-toggle" data-i18n="controls.show_cop">显示 COP</label>
                </div>
              </div>"""
        return new_html

    content = re.sub(controls_pattern, controls_repl, content, flags=re.DOTALL)
    
    # 2. Generate 4 panels
    # 定义单个面板的模板
    panel_template = """
                <section class="heatmap-panel {d_none_class}" aria-labelledby="panel-{i}-label" id="panel-{i}">
                  <div class="heatmap-panel-header">
                    <h3 class="h6 mb-0" id="panel-{i}-label" data-i18n="controls.panel_label" data-i18n-options='{{"index": {display_index}}}'>设备 {display_index}</h3>
                  </div>
                  <div class="heatmap-panel-controls">
                    <div class="input-group mb-2">
                      <span class="input-group-text" data-i18n="controls.device_label" data-i18n-options='{{"index": {display_index}}}'>设备 {display_index}</span>
                      <select class="form-select" id="device-selector-{i}" disabled>
                        <option value="" data-i18n="controls.waiting">等待数据...</option>
                      </select>
                    </div>
                    <div class="input-group mb-2">
                      <span class="input-group-text" data-i18n="controls.layout">布局</span>
                      <select class="form-select" id="layout-selector-{i}" disabled>
                        <option value="">--</option>
                      </select>
                    </div>
                    <div class="mirror-toggle-group d-flex flex-wrap align-items-center gap-3">
                      <div class="form-check form-switch mb-0">
                        <input class="form-check-input" type="checkbox" id="mirror-rows-{i}" />
                        <label class="form-check-label" for="mirror-rows-{i}" data-i18n="controls.mirror_rows">行镜像</label>
                      </div>
                      <div class="form-check form-switch mb-0">
                        <input class="form-check-input" type="checkbox" id="mirror-cols-{i}" />
                        <label class="form-check-label" for="mirror-cols-{i}" data-i18n="controls.mirror_cols">列镜像</label>
                      </div>
                    </div>
                  </div>
                  <div class="heatmap-wrapper" id="heatmap-container-{i}">
                    <div class="heatmap-placeholder" data-i18n="heatmap.empty.waiting">等待数据...</div>
                  </div>
                  <div class="device-metrics">
                    <div class="device-sensor-grid">
                      <div class="overview-sensor-block">
                        <div class="fw-semibold" data-i18n="overview.gyro">陀螺仪 (°/s)</div>
                        <div class="sensor-vector">
                          <div class="axis-value"><span>X</span><strong id="gyro-{i}-x">--</strong></div>
                          <div class="axis-value"><span>Y</span><strong id="gyro-{i}-y">--</strong></div>
                          <div class="axis-value"><span>Z</span><strong id="gyro-{i}-z">--</strong></div>
                        </div>
                      </div>
                      <div class="overview-sensor-block">
                        <div class="fw-semibold" data-i18n="overview.acc">加速度 (m/s²)</div>
                        <div class="sensor-vector">
                          <div class="axis-value"><span>X</span><strong id="acc-{i}-x">--</strong></div>
                          <div class="axis-value"><span>Y</span><strong id="acc-{i}-y">--</strong></div>
                          <div class="axis-value"><span>Z</span><strong id="acc-{i}-z">--</strong></div>
                        </div>
                      </div>
                    </div>
                    <div class="overview-sensor-block mt-3 cop-container" id="cop-container-{i}">
                      <div class="fw-semibold" data-i18n="overview.cop">压力中心 (COP)</div>
                      <div class="cop-board" id="cop-board-{i}">
                        <div class="cop-board-placeholder" id="cop-placeholder-{i}" data-i18n="overview.cop_empty">等待设备数据...</div>
                        <div class="cop-dot" id="cop-dot-{i}"></div>
                      </div>
                      <div class="row text-center cop-values mt-3">
                        <div class="col">
                          <div class="text-muted small" data-i18n="overview.cop_x">X 坐标</div>
                          <div class="fw-semibold" id="cop-x-{i}">--</div>
                        </div>
                        <div class="col">
                          <div class="text-muted small" data-i18n="overview.cop_y">Y 坐标</div>
                          <div class="fw-semibold" id="cop-y-{i}">--</div>
                        </div>
                      </div>
                    </div>
                  </div>
                </section>"""

    new_grid_content = ""
    for i in range(4):
        d_none = "d-none" if i > 0 else ""
        new_grid_content += panel_template.format(i=i, display_index=i+1, d_none_class=d_none) + "\n"

    # 替换 dual-heatmap-grid 的内容
    grid_pattern = r'(<div class="dual-heatmap-grid">)(.*?)(</div>\s*</div>\s*</div>\s*</div>\s*</div>)' 
    # 注意：上面的正则可能太贪婪或者不匹配嵌套 div。更安全的是找到 class="dual-heatmap-grid"> 到 紧接着的两个 section 结束。
    
    # 使用简单的标记查找
    start_marker = '<div class="dual-heatmap-grid">'
    end_marker = '<!-- Device table showing latest snapshot per DN -->'
    
    start_idx = content.find(start_marker)
    if start_idx != -1:
        # 找到 grid 结束位置。可以通过查找下一个大的 block (device table) 来定位
        end_idx = content.find(end_marker)
        
        # 往前找 grid 的闭合 div。
        # 现有的结构：
        # <div class="dual-heatmap-grid">
        #   <section ...> ... </section>
        #   <section ...> ... </section>
        # </div>
        # </div> <!-- card-body -->
        # </div> <!-- card -->
        # </div> <!-- col-12 -->
        # </div> <!-- row g-4 -->
        
        # 为了安全，我们只替换 <div class="dual-heatmap-grid"> 内部的内容
        # 但我们想完全替换里面的 sections
        
        # 让我们尝试正则匹配内部的 sections
        inner_pattern = r'(<div class="dual-heatmap-grid">\s*)(<section.*?section>\s*<section.*?section>)(\s*</div>)'
        
        def grid_repl(match):
            return match.group(1) + new_grid_content + match.group(3)
        
        content = re.sub(inner_pattern, grid_repl, content, flags=re.DOTALL)
    
    return content

def update_js(content):
    # 1. Update panelContexts definition
    old_panels = r'const panelContexts = \["primary", "secondary"\]\.map\(\(key\) => \(\{.*?\}\)\);'
    new_panels = """const panelContexts = [0, 1, 2, 3].map((i) => {
        const key = String(i);
        return {
          key,
          panelElement: document.getElementById(`panel-${key}`),
          deviceSelector: document.getElementById(`device-selector-${key}`),
          layoutSelector: document.getElementById(`layout-selector-${key}`),
          heatmapContainer: document.getElementById(`heatmap-container-${key}`),
          mirrorRowsToggle: document.getElementById(`mirror-rows-${key}`),
          mirrorColsToggle: document.getElementById(`mirror-cols-${key}`),
          gyroElements: {
            x: document.getElementById(`gyro-${key}-x`),
            y: document.getElementById(`gyro-${key}-y`),
            z: document.getElementById(`gyro-${key}-z`)
          },
          accElements: {
            x: document.getElementById(`acc-${key}-x`),
            y: document.getElementById(`acc-${key}-y`),
            z: document.getElementById(`acc-${key}-z`)
          },
          copContainer: document.getElementById(`cop-container-${key}`),
          copBoard: document.getElementById(`cop-board-${key}`),
          copDot: document.getElementById(`cop-dot-${key}`),
          copPlaceholder: document.getElementById(`cop-placeholder-${key}`),
          copXValue: document.getElementById(`cop-x-${key}`),
          copYValue: document.getElementById(`cop-y-${key}`),
          selectedDevice: null,
          selectedLayoutKey: null,
          mirrorRows: false,
          mirrorCols: false,
          deviceOptionsCache: { devices: [], selected: null, lang: null },
          layoutOptionsCache: { dn: null, sensorCount: null, options: [], selectedKey: null, lang: null }
        };
      });"""
    
    content = re.sub(old_panels, new_panels, content, flags=re.DOTALL)

    # 2. Update toggle references
    content = content.replace('const dualModeToggle = document.getElementById("dual-mode-toggle");', 
                              'const multiModeToggle = document.getElementById("multi-mode-toggle");\n      const copVisibilityToggle = document.getElementById("cop-visibility-toggle");')
    
    content = content.replace('let dualModeEnabled = localStorage.getItem("dualModeEnabled") === "1";', 
                              'let multiModeEnabled = localStorage.getItem("multiModeEnabled") === "1";\n      let copVisible = localStorage.getItem("copVisible") !== "0";') # Default to true
    
    # 3. Update references to primary/secondary panels
    # content = content.replace('const primaryPanel = panelContexts[0];', '') # Not strictly needed if logic is generic
    # content = content.replace('const secondaryPanel = panelContexts[1];', '')
    
    # 4. Update panelIsActive logic
    # Old: return panel.key !== "secondary" || dualModeEnabled;
    # New: if panel is 0, always active. If > 0, active if multiModeEnabled.
    old_isActive = r'function panelIsActive\(panel\) \{.*?\}'
    new_isActive = """function panelIsActive(panel) {
        const idx = Number(panel.key);
        return idx === 0 || multiModeEnabled;
      }"""
    content = re.sub(old_isActive, new_isActive, content, flags=re.DOTALL)

    # 5. Update setDualMode -> setMultiMode
    old_setDual = r'function setDualMode\(enabled\) \{.*?\}'
    new_setMulti = """function setMultiMode(enabled) {
        multiModeEnabled = enabled;
        localStorage.setItem("multiModeEnabled", enabled ? "1" : "0");
        applyMultiModeState();
        updateDeviceOptions();
        panelContexts.forEach((panel) => updateLayoutOptionsForPanel(panel));
        panelContexts.forEach(updatePanelSensors);
        updateAllHeatmaps();
        panelContexts.forEach(updatePanelCop);
      }
      
      function setCopVisibility(visible) {
        copVisible = visible;
        localStorage.setItem("copVisible", visible ? "1" : "0");
        panelContexts.forEach(panel => {
           if (panel.copContainer) {
               panel.copContainer.classList.toggle("d-none", !visible);
           }
        });
      }"""
    content = re.sub(old_setDual, new_setMulti, content, flags=re.DOTALL)

    # 6. Update applyDualModeState -> applyMultiModeState
    old_applyDual = r'function applyDualModeState\(\)
 \{.*?\}'
    new_applyMulti = """function applyMultiModeState() {
        if (multiModeToggle) {
          multiModeToggle.checked = multiModeEnabled;
        }
        if (copVisibilityToggle) {
          copVisibilityToggle.checked = copVisible;
        }
        
        // Update panels 1, 2, 3 visibility
        panelContexts.forEach((panel, idx) => {
            if (idx > 0 && panel.panelElement) {
                panel.panelElement.classList.toggle("d-none", !multiModeEnabled);
            }
            if (panel.copContainer) {
                panel.copContainer.classList.toggle("d-none", !copVisible);
            }
        });
      }"""
    content = re.sub(old_applyDual, new_applyMulti, content, flags=re.DOTALL)

    # 7. Update listeners
    # if (dualModeToggle) ...
    old_listeners = r'if \(dualModeToggle\) \{.*?applyDualModeState\(\);'
    new_listeners = """if (multiModeToggle) {
        multiModeToggle.checked = multiModeEnabled;
        multiModeToggle.addEventListener("change", (event) => {
          setMultiMode(Boolean(event.target.checked));
        });
      }
      if (copVisibilityToggle) {
        copVisibilityToggle.checked = copVisible;
        copVisibilityToggle.addEventListener("change", (event) => {
            setCopVisibility(Boolean(event.target.checked));
        });
      }
      applyMultiModeState();"""
    content = re.sub(old_listeners, new_listeners, content, flags=re.DOTALL)

    # 8. Update translations
    # Need to update keys: controls.dual_mode -> controls.multi_mode
    # And add controls.show_cop
    # And update device labels logic
    
    # We can handle translation updates by replacing the TRANSLATIONS object content or adding to it.
    # Since regex for object replacement is tricky, let's just inject new keys.
    
    content = content.replace('"controls.dual_mode": "双设备模式"', '"controls.multi_mode": "多设备模式",\n          "controls.show_cop": "显示 COP",\n          "controls.panel_label": "设备 {{index}}",\n          "controls.device_label": "设备 {{index}}"')
    content = content.replace('"controls.dual_mode": "デュアル表示"', '"controls.multi_mode": "マルチデバイス",\n          "controls.show_cop": "COPを表示",\n          "controls.panel_label": "デバイス {{index}}",\n          "controls.device_label": "デバイス {{index}}"')
    content = content.replace('"controls.dual_mode": "Dual mode"', '"controls.multi_mode": "Multi-device",\n          "controls.show_cop": "Show COP",\n          "controls.panel_label": "Device {{index}}",\n          "controls.device_label": "Device {{index}}"')
    
    # Fix heatmap empty msg key
    content = content.replace('"heatmap.empty.dual_disabled": "开启双设备模式以查看第二设备"', '"heatmap.empty.dual_disabled": "开启多设备模式以查看更多设备"')
    content = content.replace('"heatmap.empty.dual_disabled": "デュアル表示を有効にすると表示されます"', '"heatmap.empty.dual_disabled": "マルチモードを有効にする"')
    content = content.replace('"heatmap.empty.dual_disabled": "Enable dual mode to visualize the second device"', '"heatmap.empty.dual_disabled": "Enable multi-device mode"')

    # 9. Update chooseDefaultDeviceForPanel logic
    # Old logic: if secondary, pick something not primary.
    # New logic: pick device at index if available, or just greedy allocation?
    # Simple logic: panel i tries to pick devices[i]
    old_choose = r'function chooseDefaultDeviceForPanel\(panel, devices\) \{.*?\}'
    new_choose = """function chooseDefaultDeviceForPanel(panel, devices) {
        const idx = Number(panel.key);
        if (panel.selectedDevice && devices.includes(panel.selectedDevice)) {
          return panel.selectedDevice;
        }
        // Try to map panel index to device index directly
        if (idx < devices.length) {
            return devices[idx];
        }
        // Fallback: pick the first one not used by previous panels? 
        // For simplicity, just return the first available or null.
        return devices[0] || null;
      }"""
    content = re.sub(old_choose, new_choose, content, flags=re.DOTALL)
    
    # 10. Fix t() function to handle interpolation for "Device {{index}}"
    # The existing t() doesn't seem to support options. 
    # HTML uses data-i18n-options, but t(key) call in code doesn't.
    # We added data-i18n-options in HTML.
    # We need to update applyLanguage to handle options.
    
    old_applyLanguage = r'function applyLanguage\(\)
 \{.*?document\.querySelectorAll\(\"\\[data-i18n\\]\"\\[\].forEach\(\(el \) => \{
.*?\}\);'
    new_applyLanguage = """function applyLanguage() {
        const locale = LANGUAGE_META[currentLanguage]?.locale || "ja-JP";
        document.documentElement.lang = locale;
        document.title = t("page.title");
        document.querySelectorAll("[data-i18n]").forEach((el) => {
          const key = el.dataset.i18n;
          if (!key) return;
          let translation = t(key);
          if (translation !== undefined) {
            // Check for options
            if (el.dataset.i18nOptions) {
                try {
                    const options = JSON.parse(el.dataset.i18nOptions);
                    for (const [k, v] of Object.entries(options)) {
                        translation = translation.replace(`{{${k}}}`, v);
                    }
                } catch (e) { console.error("Bad i18n options", e); }
            }
            el.textContent = translation;
          }
        });"""
    # Note: Regex replacement here is tricky because we need to match the whole function body or just the loop.
    # Let's try replacing the loop part specifically.
    
    loop_pattern = r'document\.querySelectorAll\(\"\\[data-i18n\\]\"\\[\].forEach\(\(el \) => \{
.*?\}\);'
    loop_repl = """document.querySelectorAll("[data-i18n]").forEach((el) => {
          const key = el.dataset.i18n;
          if (!key) return;
          let translation = t(key);
          if (translation !== undefined) {
            if (el.dataset.i18nOptions) {
                try {
                    const options = JSON.parse(el.dataset.i18nOptions);
                    Object.entries(options).forEach(([k, v]) => {
                        translation = translation.replace(`{{${k}}}`, v);
                    });
                } catch (e) {}
            }
            el.textContent = translation;
          }
        });"""
    content = re.sub(loop_pattern, loop_repl, content, flags=re.DOTALL)
    
    return content

if __name__ == "__main__":
    with open('webapp/templates/index.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    content = update_html(content)
    content = update_js(content)
    
    with open('webapp/templates/index.html', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("Successfully updated webapp/templates/index.html")
