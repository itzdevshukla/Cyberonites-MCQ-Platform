const { app, BrowserWindow, globalShortcut, session, dialog, clipboard, desktopCapturer, net, screen } = require('electron');
const { autoUpdater } = require('electron-updater');
const { exec, spawn } = require('child_process');
const crypto = require('crypto');
const path = require('path');
const fs = require('fs');

// Register custom deep linking protocol (qarena://)
if (process.defaultApp) {
    if (process.argv.length >= 2) {
        app.setAsDefaultProtocolClient('qarena', process.execPath, [path.resolve(process.argv[1])]);
    }
} else {
    app.setAsDefaultProtocolClient('qarena');
}

// Enforce single application instance
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
    app.quit();
}

// Disable touchpad overscroll history navigation, Windows Edge Gestures (Action Center / Task View swipes), and pinch zoom
app.commandLine.appendSwitch('disable-features', 'TouchpadOverscrollHistoryNavigation,OverscrollHistoryNavigation,WindowsEdgeGestures,SwipeToNavigate');
app.commandLine.appendSwitch('disable-pinch');
app.commandLine.appendSwitch('kiosk');

// Asymmetric Cryptographic Attestation (Zero Static Secrets)
// Generates ephemeral Ed25519 key pair in volatile RAM on launch
const { publicKey: clientPublicKeyObj, privateKey: clientPrivateKeyObj } = crypto.generateKeyPairSync('ed25519');
const rawPubSpki = clientPublicKeyObj.export({ type: 'spki', format: 'der' });
// Extract raw 32-byte Ed25519 public key (last 32 bytes of SPKI DER)
const CLIENT_PUBLIC_KEY_HEX = rawPubSpki.subarray(rawPubSpki.length - 32).toString('hex');
console.log(`[Security] Ephemeral Ed25519 Attestation Key Initialized: ${CLIENT_PUBLIC_KEY_HEX.substring(0, 12)}...`);

// Read config.json for custom hosting (Router LAN IP, Domain, or custom server)
let customConfig = {};
try {
    const candidatePaths = [
        path.join(path.dirname(process.execPath), 'config.json'),
        process.resourcesPath ? path.join(process.resourcesPath, 'config.json') : null,
        path.join(__dirname, 'config.json')
    ];
    for (const p of candidatePaths) {
        if (p && fs.existsSync(p)) {
            customConfig = JSON.parse(fs.readFileSync(p, 'utf8'));
            console.log(`[Config] Loaded configuration from: ${p}`);
            break;
        }
    }
} catch (e) {
    console.warn('[Config] Error reading config.json:', e.message);
}

// CLI argument override: e.g. "Cyberonites Secure Browser.exe" --url="http://192.168.1.50:8000/quiz/"
const cliUrlArg = process.argv.find(arg => arg.startsWith('--url=') || arg.startsWith('--exam-url='));
const CLI_URL = cliUrlArg ? cliUrlArg.split('=')[1].replace(/^["']|["']$/g, '') : null;

// Support router LAN IP (e.g. 192.168.1.50) or custom domain
const PRODUCTION_EXAM_URL = customConfig.production_exam_url || 'https://www.abhirajsinghchauhan.in/quiz/';
const LOCAL_DEV_EXAM_URL = customConfig.exam_url || 'http://127.0.0.1:8000/quiz/';

// Final URL resolution: CLI arg > ENV var > config.json (exam_url or production_exam_url) > default
const EXAM_URL = CLI_URL || process.env.EXAM_URL || customConfig.exam_url || (app.isPackaged ? PRODUCTION_EXAM_URL : (process.env.NODE_ENV === 'production' ? PRODUCTION_EXAM_URL : LOCAL_DEV_EXAM_URL));

function parseDeepLink(urlStr) {
    if (!urlStr || typeof urlStr !== 'string') return null;
    try {
        const clean = urlStr.replace(/^qarena:\/\//i, '').replace(/^\/+/, '');
        const baseUrl = PRODUCTION_EXAM_URL.replace(/\/quiz\/?$/, '');
        return `${baseUrl}/${clean}`;
    } catch (e) {
        return null;
    }
}

app.on('second-instance', (event, commandLine) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
        if (mainWindow.isMinimized()) mainWindow.restore();
        mainWindow.focus();
        const deepLinkUrl = commandLine.find(arg => typeof arg === 'string' && arg.startsWith('qarena://'));
        if (deepLinkUrl) {
            const target = parseDeepLink(deepLinkUrl);
            if (target) mainWindow.loadURL(target);
        }
    }
});

app.on('open-url', (event, url) => {
    event.preventDefault();
    if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.focus();
        const target = parseDeepLink(url);
        if (target) mainWindow.loadURL(target);
    }
});

let mainWindow = null;
let monitoringInterval = null;
let focusEnforcerInterval = null;

// Exact prohibited process base names (without .exe) mapped to human-readable names
const PROHIBITED_MAP = {
    // Screenshot & Snipping Tools
    'snippingtool': 'Windows Snipping Tool',
    'screenclippinghost': 'Windows Screen Clipping Host',
    'snipaste': 'Snipaste Screenshot Tool',
    'lightshot': 'Lightshot Screenshot Tool',
    'sharex': 'ShareX Screen Capture',
    'greenshot': 'Greenshot Screenshot Tool',
    'flameshot': 'Flameshot Screenshot Tool',
    'screencapture': 'macOS Screen Capture Utility',
    'screencaptureui': 'macOS Screen Capture UI',
    'cleanshot x': 'CleanShot X Screen Capture',
    'cleanshot': 'CleanShot X Screen Capture',
    'shottr': 'Shottr Screenshot Tool',
    'snagit': 'Snagit Screen Capture',

    // Remote Tools & Screen Sharing
    'anydesk': 'AnyDesk Remote Desktop',
    'teamviewer': 'TeamViewer',
    'teamviewer_service': 'TeamViewer Service',
    'rustdesk': 'RustDesk',
    'ultraviewer': 'UltraViewer',
    'ultraviewer_desktop': 'UltraViewer',
    'parsec': 'Parsec Gaming/Remote Desktop',
    'parsecd': 'Parsec Daemon',
    'mstsc': 'Windows Remote Desktop Connection',
    'vncviewer': 'VNC Viewer',
    'vncserver': 'VNC Server',
    'winvnc': 'WinVNC Server',
    'tor': 'Tor Browser',
    'torbrowser': 'Tor Browser',

    // Screen Recorders & Streaming
    'obs64': 'OBS Studio (64-bit)',
    'obs32': 'OBS Studio (32-bit)',
    'obs': 'OBS Studio',
    'camtasia': 'Camtasia Screen Recorder',
    'camtasiastudio': 'Camtasia Studio',
    'bdcam': 'Bandicam Screen Recorder',
    'bandicam': 'Bandicam Screen Recorder',
    'fraps': 'Fraps Video Capture',
    'streamlabs obs': 'Streamlabs OBS',
    'streamlabs': 'Streamlabs',
    'action': 'Mirillis Action! Screen Recorder',
    'quicktime player': 'QuickTime Player Screen Recorder',
    'quicktimeplayer': 'QuickTime Player Screen Recorder',

    // Messaging & Collaboration
    'discord': 'Discord',
    'skype': 'Skype',
    'zoom': 'Zoom Meetings',
    'teams': 'Microsoft Teams',
    'msteams': 'Microsoft Teams',
    'webexhost': 'Cisco Webex',
    'ciscowebexstart': 'Cisco Webex',
    'slack': 'Slack',
    'telegram': 'Telegram Desktop',
    'whatsapp': 'WhatsApp Desktop',
    'facetime': 'Apple FaceTime',

    // Virtual Machines
    'virtualbox': 'Oracle VirtualBox',
    'virtualboxvm': 'VirtualBox VM',
    'vboxmanage': 'VirtualBox Manager',
    'vboxsvc': 'VirtualBox Service',
    'vmware': 'VMware Workstation',
    'vmware-vmx': 'VMware Virtual Machine',
    'qemu-system-x86_64': 'QEMU Virtual Machine',
    'qemu-system-i386': 'QEMU Virtual Machine',
    'qemu': 'QEMU Emulator',
    'parallels': 'Parallels Desktop VM',
    'prl_client_app': 'Parallels Desktop Virtual Machine',
    'prl_vm_app': 'Parallels Desktop Virtual Machine',
    'utm': 'UTM Virtual Machine'
};

/**
 * Get running process names natively without any external dependencies.
 */
function getRunningProcesses() {
    return new Promise((resolve) => {
        if (process.platform === 'win32') {
            exec('tasklist /fo csv /nh', { windowsHide: true }, (err, stdout) => {
                if (err || !stdout) return resolve([]);
                const lines = stdout.split('\r\n');
                const procs = [];
                for (const line of lines) {
                    const match = line.match(/^"([^"]+)"/);
                    if (match) procs.push(match[1].toLowerCase());
                }
                resolve(procs);
            });
        } else {
            exec('ps -A -o comm=', (err, stdout) => {
                if (err || !stdout) return resolve([]);
                const lines = stdout.split('\n').map(l => l.trim().toLowerCase()).filter(Boolean);
                resolve(lines);
            });
        }
    });
}

/**
 * Check if multiple monitors/displays (e.g. external HDMI, TV, projector) are connected.
 */
function checkMultiMonitor() {
    try {
        if (!screen) return null;
        const displays = screen.getAllDisplays();
        if (displays && displays.length > 1) {
            return `Multi-Monitor Display Detected (${displays.length} displays active). Please disconnect all external monitors/HDMI cables to continue.`;
        }
    } catch (e) {}
    return null;
}

/**
 * Deep pre-flight inspection for Virtual Machines (VMware, VirtualBox, QEMU, Hyper-V, Parallels)
 * and Remote Desktop Sessions (Windows RDP, Terminal Services, Citrix, Cloud VPS, Virtual Displays).
 */
function checkVirtualMachineAndRDP() {
    return new Promise((resolve) => {
        // macOS Hypervisor check
        if (process.platform === 'darwin') {
            exec('sysctl -n machdep.cpu.brand_string', { windowsHide: true }, (err, stdout) => {
                if (!err && stdout) {
                    const s = stdout.toLowerCase();
                    if (s.includes('qemu') || s.includes('virtual') || s.includes('vmware') || s.includes('parallels')) {
                        return resolve('Virtual Machine Environment Detected (macOS Hypervisor)');
                    }
                }
                resolve(null);
            });
            return;
        }

        if (process.platform !== 'win32') {
            return resolve(null);
        }

        // 1. Instant RDP Environment & Session Variables Check (< 1ms)
        const clientName = process.env.CLIENTNAME || '';
        const sessionName = (process.env.SESSIONNAME || '').toUpperCase();
        if (clientName.length > 0 || (sessionName && sessionName.includes('RDP'))) {
            return resolve(`Remote Desktop (RDP) Session Detected (Client: ${clientName || 'Remote Session'})`);
        }

        // 2. Fast Windows Registry BIOS & System Model Check (< 25ms)
        exec('reg query "HKLM\\HARDWARE\\Description\\System\\BIOS"', { windowsHide: true }, (err, stdout) => {
            if (!err && stdout) {
                const text = stdout.toLowerCase();
                const vmKeywords = ['virtualbox', 'vmware', 'qemu', 'innotek', 'parallels', 'hyper-v', 'xen'];
                for (const kw of vmKeywords) {
                    if (text.includes(kw)) {
                        return resolve(`Virtual Machine Environment Detected (BIOS Signature: ${kw.toUpperCase()})`);
                    }
                }
                if (text.includes('virtual machine') && text.includes('microsoft corporation')) {
                    return resolve('Virtual Machine Detected (Microsoft Hyper-V)');
                }
            }

            // 3. Display Adapter & Virtual GPU Driver Check (catches RDP, Parsec, VirtualBox video drivers)
            exec('powershell -NoProfile -Command "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"', { windowsHide: true, timeout: 1500 }, (pErr, pStdout) => {
                if (!pErr && pStdout) {
                    const gpus = pStdout.toLowerCase();
                    const remoteGpus = [
                        'microsoft remote display',
                        'citrix',
                        'parsec virtual display',
                        'iddsample',
                        'vboxvideo',
                        'vmware svga',
                        'qemu standard'
                    ];
                    for (const rGpu of remoteGpus) {
                        if (gpus.includes(rGpu)) {
                            return resolve(`Remote/Virtual Display Adapter Detected (${rGpu.toUpperCase()})`);
                        }
                    }
                }

                // 4. Volatile Environment RDP Client Registry Check
                exec('reg query "HKCU\\Volatile Environment" /v CLIENTNAME', { windowsHide: true }, (vErr, vStdout) => {
                    if (!vErr && vStdout && vStdout.includes('CLIENTNAME')) {
                        return resolve('Remote Terminal Services Client Connection Detected');
                    }

                    // 5. SystemInformation Registry Fallback
                    exec('reg query "HKLM\\SYSTEM\\CurrentControlSet\\Control\\SystemInformation"', { windowsHide: true }, (rErr, rStdout) => {
                        if (!rErr && rStdout) {
                            const rText = rStdout.toLowerCase();
                            const rKeywords = ['virtualbox', 'vmware', 'qemu', 'xen', 'parallels'];
                            for (const rkw of rKeywords) {
                                if (rText.includes(rkw)) {
                                    return resolve(`Virtual Machine Detected (${rkw.toUpperCase()})`);
                                }
                            }
                        }
                        resolve(null);
                    });
                });
            });
        });
    });
}

// Whitelist OEM gaming laptop background services (HP OMEN, Asus ROG, Lenovo Vantage, Dell, MSI, etc.)
// Prevents proprietary hardware helper services from ever being falsely flagged or interfering with the exam.
const OEM_SYSTEM_WHITELIST_KEYWORDS = [
    'omen', 'hp', 'hewlett', 'dell', 'alienware', 'asus', 'rog', 
    'armoury', 'lenovo', 'vantage', 'msi', 'dragon', 'razer', 'logitech', 
    'corsair', 'icue', 'intel', 'amd', 'nvidia', 'realtek', 'geforce',
    'system', 'svchost', 'runtimebroker', 'shellexperiencehost', 'searchhost',
    'audiostudio', 'waves', 'nahimic', 'killer', 'gamebar', 'conhost',
    'casl', 'touchpoint', 'synaptics', 'elan', 'alps', 'wmi', 'spoolsv'
];

function isWhitelistedProcess(rawName) {
    if (!rawName) return true;
    const lower = rawName.toLowerCase();
    if (lower.includes('secure-app') || lower.includes('electron') || lower.includes('cyberonites') || lower.includes('qarena')) {
        return true;
    }
    if (lower === 'msedgewebview2.exe' || lower === 'msedgewebview2') {
        return true;
    }
    return OEM_SYSTEM_WHITELIST_KEYWORDS.some(k => lower.includes(k));
}

/**
 * Scan for physical hardware violations (multi-monitor, VM/RDP).
 * Used for pre-flight check on app launch. Background processes are NOT checked here
 * so students are never blocked from launching the browser.
 */
async function checkHardwareViolations() {
    try {
        const multiMon = checkMultiMonitor();
        if (multiMon) return multiMon;

        const vmOrRdp = await checkVirtualMachineAndRDP();
        if (vmOrRdp) return vmOrRdp;
    } catch (e) {
        console.error('Error during hardware check:', e);
    }
    return null;
}

/**
 * Passively scan for prohibited tools (AnyDesk, TeamViewer, OBS, etc.).
 * Returns human-readable violation string or null.
 */
async function checkProhibitedProcesses() {
    try {
        const processes = await getRunningProcesses();
        for (const raw of processes) {
            if (isWhitelistedProcess(raw)) {
                continue;
            }
            const base = raw.replace(/\.exe$/, '').trim();
            if (PROHIBITED_MAP[base]) {
                return `${PROHIBITED_MAP[base]} (${raw})`;
            }
        }
    } catch (e) {
        console.error('Error checking running processes:', e);
    }
    return null;
}

/**
 * Authoritative out-of-band security violation reporting directly from Electron Main Process.
 * Bypasses webpage DOM completely, ensuring delivery cannot be intercepted, silenced, or dropped.
 */
async function reportNativeViolation(type, details) {
    if (!mainWindow || mainWindow.isDestroyed()) return;

    try {
        const currentUrl = mainWindow.webContents.getURL();
        if (!currentUrl) return;

        let parsedUrl;
        try {
            parsedUrl = new URL(currentUrl);
        } catch (e) {
            return;
        }

        const match = parsedUrl.pathname.match(/\/quiz\/(\d+)/);
        const quizId = match ? match[1] : null;

        // Show UI warning toast inside web view if alive
        const sanitizedDetails = String(details || '').replace(/['"\\]/g, '');
        mainWindow.webContents.executeJavaScript(`
            if (typeof showToast === 'function') {
                showToast('⚠️ Security Violation Detected: ${sanitizedDetails}', 'warning', 5000);
            }
        `).catch(() => {});

        if (!quizId) {
            // Not in an active quiz attempt (e.g. login page or quiz list)
            return;
        }

        // Fetch session cookies from Electron session
        const cookies = await session.defaultSession.cookies.get({ url: parsedUrl.origin });
        const csrfCookie = cookies.find(c => c.name === 'csrftoken');
        const csrfToken = csrfCookie ? csrfCookie.value : '';

        const endpoint = `${parsedUrl.origin}/quiz/${quizId}/violation/`;

        // Direct Node/Electron native network request (bypasses webpage DOM completely)
        // Automatically signed with Ed25519 headers in onBeforeSendHeaders
        const response = await net.fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken,
                'X-Requested-With': 'XMLHttpRequest',
            },
            body: JSON.stringify({
                type: type,
                details: details,
            }),
            credentials: 'include',
        });

        if (response.ok) {
            const data = await response.json().catch(() => ({}));
            console.log(`[Security] Native violation [${type}] successfully recorded by server:`, data);

            // If auto-submitted due to reaching max violations, redirect page to results
            if (data && data.auto_submitted) {
                mainWindow.loadURL(`${parsedUrl.origin}/dashboard/result/${quizId}/`).catch(() => {});
            }
            return data;
        } else {
            console.warn(`[Security] Violation report received HTTP status ${response.status}`);
        }
    } catch (err) {
        console.error('[Security] Failed to deliver native violation report:', err.message);
    }
}

/**
 * Start periodic monitoring every 6 seconds (lightweight background scan).
 */
const reportedProcessesCooldown = new Map();

/**
 * Start periodic passive monitoring every 6 seconds.
 * Monitors and logs background violations to the server WITHOUT abruptly crashing or killing the student's exam.
 */
function startMonitoring() {
    if (monitoringInterval) clearInterval(monitoringInterval);
    monitoringInterval = setInterval(async () => {
        try {
            // 1. Dynamic multi-monitor check (e.g. HDMI display plugged in mid-exam)
            const multiMon = checkMultiMonitor();
            if (multiMon && mainWindow && !mainWindow.isDestroyed()) {
                const now = Date.now();
                const last = reportedProcessesCooldown.get('MULTI_MON') || 0;
                if (now - last > 30000) {
                    reportedProcessesCooldown.set('MULTI_MON', now);
                    reportNativeViolation('VM_DETECTED', multiMon);
                }
            }

            // 2. Passive prohibited process monitoring (AnyDesk, TeamViewer, OBS, etc.)
            const detectedProcess = await checkProhibitedProcesses();
            if (detectedProcess && mainWindow && !mainWindow.isDestroyed()) {
                const now = Date.now();
                const last = reportedProcessesCooldown.get(detectedProcess) || 0;
                // Throttle reporting to once per 30 seconds per detected process
                if (now - last > 30000) {
                    reportedProcessesCooldown.set(detectedProcess, now);
                    console.warn(`[Security Monitor] Background prohibited tool detected: ${detectedProcess}`);

                    // Report natively out-of-band to server for proctor forensic logs
                    reportNativeViolation('PROHIBITED_PROCESS', `Prohibited background tool active: ${detectedProcess}`);

                    // Subtle non-blocking in-app notification to warn candidate without killing exam
                    const safeName = detectedProcess.replace(/['"\\]/g, '');
                    mainWindow.webContents.executeJavaScript(`
                        if (typeof showToast === 'function') {
                            showToast('⚠️ Proctor Notice: Background application (${safeName}) is active and being monitored.', 'warning', 5000);
                        }
                    `).catch(() => {});
                }
            }
        } catch (e) {
            console.error('[Security Monitor] Error during background check cycle:', e);
        }
    }, 6000);
}

let isExitingDialogActive = false;
let isEnvironmentActive = false;

/**
 * Pod.ai & Safe Exam Browser (SEB) Kiosk Environment Isolation Engine:
 * 1. Overrides Windows Precision Touchpad registry to disable 3-finger & 4-finger slides.
 * 2. Launches a detached PowerShell supervisor watchdog to guarantee registry is restored on exit/crash.
 * 3. Preserves Windows Explorer (explorer.exe) running so OEM utilities (HP OMEN, Asus, Dell) remain stable.
 */
function disableTouchpadGesturesRegistry() {
    if (process.platform !== 'win32') return;
    try {
        const cmd = [
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v ThreeFingerSlideEnabled /t REG_DWORD /d 0 /f',
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v ThreeFingerTapEnabled /t REG_DWORD /d 0 /f',
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v ThreeFingerUp /t REG_DWORD /d 0 /f',
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v ThreeFingerDown /t REG_DWORD /d 0 /f',
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v ThreeFingerLeft /t REG_DWORD /d 0 /f',
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v ThreeFingerRight /t REG_DWORD /d 0 /f',
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v FourFingerSlideEnabled /t REG_DWORD /d 0 /f',
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v FourFingerTapEnabled /t REG_DWORD /d 0 /f',
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v FourFingerUp /t REG_DWORD /d 0 /f',
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v FourFingerDown /t REG_DWORD /d 0 /f',
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v FourFingerLeft /t REG_DWORD /d 0 /f',
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v FourFingerRight /t REG_DWORD /d 0 /f'
        ].join(' & ');
        exec(cmd, { windowsHide: true }, () => {});
    } catch (e) {}
}

function restoreTouchpadGesturesRegistry() {
    if (process.platform !== 'win32') return;
    try {
        const cmd = [
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v ThreeFingerSlideEnabled /t REG_DWORD /d 1 /f',
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v ThreeFingerTapEnabled /t REG_DWORD /d 1 /f',
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v ThreeFingerUp /t REG_DWORD /d 2 /f',
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v ThreeFingerDown /t REG_DWORD /d 3 /f',
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v ThreeFingerLeft /t REG_DWORD /d 1 /f',
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v ThreeFingerRight /t REG_DWORD /d 1 /f',
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v FourFingerSlideEnabled /t REG_DWORD /d 2 /f',
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v FourFingerTapEnabled /t REG_DWORD /d 2 /f',
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v FourFingerUp /t REG_DWORD /d 2 /f',
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v FourFingerDown /t REG_DWORD /d 3 /f',
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v FourFingerLeft /t REG_DWORD /d 4 /f',
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad" /v FourFingerRight /t REG_DWORD /d 4 /f'
        ].join(' & ');
        exec(cmd, { windowsHide: true }, () => {});
    } catch (e) {}
}

function spawnExplorerWatchdog() {
    if (process.platform !== 'win32') return;
    try {
        const pid = process.pid;
        const restoreCmd = [
            'reg add \\\"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad\\\" /v ThreeFingerSlideEnabled /t REG_DWORD /d 1 /f',
            'reg add \\\"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad\\\" /v ThreeFingerTapEnabled /t REG_DWORD /d 1 /f',
            'reg add \\\"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad\\\" /v ThreeFingerUp /t REG_DWORD /d 2 /f',
            'reg add \\\"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad\\\" /v ThreeFingerDown /t REG_DWORD /d 3 /f',
            'reg add \\\"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad\\\" /v ThreeFingerLeft /t REG_DWORD /d 1 /f',
            'reg add \\\"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad\\\" /v ThreeFingerRight /t REG_DWORD /d 1 /f',
            'reg add \\\"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad\\\" /v FourFingerSlideEnabled /t REG_DWORD /d 2 /f',
            'reg add \\\"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad\\\" /v FourFingerTapEnabled /t REG_DWORD /d 2 /f',
            'reg add \\\"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad\\\" /v FourFingerUp /t REG_DWORD /d 2 /f',
            'reg add \\\"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad\\\" /v FourFingerDown /t REG_DWORD /d 3 /f',
            'reg add \\\"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad\\\" /v FourFingerLeft /t REG_DWORD /d 4 /f',
            'reg add \\\"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PrecisionTouchPad\\\" /v FourFingerRight /t REG_DWORD /d 4 /f',
            'reg add \\\"HKCU\\Software\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon\\\" /v AutoRestartShell /t REG_DWORD /d 1 /f',
            'reg add \\\"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Policies\\System\\\" /v DisableTaskMgr /t REG_DWORD /d 0 /f'
        ].join('; ');
        const psScript = `$p = Get-Process -Id ${pid} -ErrorAction SilentlyContinue; if ($p) { $p.WaitForExit(); } ${restoreCmd}; Start-Process explorer.exe;`;
        const child = spawn('powershell', ['-NoProfile', '-WindowStyle', 'Hidden', '-Command', psScript], {
            detached: true,
            stdio: 'ignore',
            windowsHide: true
        });
        child.unref();
    } catch (e) {
        console.warn('[Security] Could not spawn shell watchdog:', e.message);
    }
}

function enterSecureKioskEnvironment() {
    if (process.platform !== 'win32' || isEnvironmentActive) return;
    isEnvironmentActive = true;
    console.log('[Security] Entering Isolated Exam Environment (Safe Exam Browser Shell Suppression)...');
    disableTouchpadGesturesRegistry();
    try {
        exec('reg add "HKCU\\Software\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon" /v AutoRestartShell /t REG_DWORD /d 0 /f', { windowsHide: true }, () => {});
        exec('reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Policies\\System" /v DisableTaskMgr /t REG_DWORD /d 1 /f', { windowsHide: true }, () => {});
    } catch (e) {}
    spawnExplorerWatchdog();
    // Temporarily suppress explorer.exe and shell experience hosts so 3-finger / 4-finger swipes CANNOT respond
    exec('taskkill /f /im explorer.exe /im ShellExperienceHost.exe /im StartMenuExperienceHost.exe', { windowsHide: true }, () => {});
}

function leaveSecureKioskEnvironment() {
    if (process.platform !== 'win32' || !isEnvironmentActive) return;
    isEnvironmentActive = false;
    console.log('[Security] Restoring Windows Desktop Shell Environment...');
    try {
        exec('reg add "HKCU\\Software\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon" /v AutoRestartShell /t REG_DWORD /d 1 /f', { windowsHide: true }, () => {});
        exec('reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Policies\\System" /v DisableTaskMgr /t REG_DWORD /d 0 /f', { windowsHide: true }, () => {});
    } catch (e) {}
    restoreTouchpadGesturesRegistry();
    exec('start explorer.exe', { windowsHide: true }, () => {});
}

function exitAppDirectly() {
    if (focusEnforcerInterval) clearInterval(focusEnforcerInterval);
    if (monitoringInterval) clearInterval(monitoringInterval);
    if (typeof snapshotInterval !== 'undefined' && snapshotInterval) clearInterval(snapshotInterval);
    if (liveStreamTimer) clearTimeout(liveStreamTimer);
    if (liveStreamWatcherInterval) clearInterval(liveStreamWatcherInterval);
    leaveSecureKioskEnvironment();
    setTimeout(() => {
        app.exit(0);
    }, 600);
}

/**
 * Custom Cyberonites Glassmorphic Dark UI Confirmation Modal
 */
const CYBER_MODAL_CSS = `
@keyframes cyberExitFadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}
@keyframes cyberExitScale {
    from { transform: scale(0.92); opacity: 0; }
    to { transform: scale(1); opacity: 1; }
}
`;

const CYBER_MODAL_SCRIPT = `
(function() {
    window.__showCyberExitModal = function() {
        if (document.getElementById('cyberonites-exit-modal-overlay')) return;
        console.log('__APP:MODAL_OPENED__');

        const overlay = document.createElement('div');
        overlay.id = 'cyberonites-exit-modal-overlay';
        overlay.style.cssText = 'position: fixed !important; inset: 0 !important; width: 100vw !important; height: 100vh !important; background: rgba(4, 8, 16, 0.85) !important; backdrop-filter: blur(14px) !important; -webkit-backdrop-filter: blur(14px) !important; z-index: 2147483647 !important; display: flex !important; align-items: center !important; justify-content: center !important; animation: cyberExitFadeIn 0.2s ease-out !important; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Inter", sans-serif !important;';

        overlay.innerHTML = \`
            <div style="background: linear-gradient(145deg, #111827, #0b0f19) !important; border: 1px solid rgba(255, 71, 87, 0.45) !important; border-radius: 18px !important; padding: 34px 38px !important; max-width: 440px !important; width: 90% !important; text-align: center !important; box-shadow: 0 25px 60px rgba(0, 0, 0, 0.85), 0 0 35px rgba(255, 71, 87, 0.25) !important; animation: cyberExitScale 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;">
                <div style="width: 58px !important; height: 58px !important; margin: 0 auto 18px !important; background: rgba(255, 71, 87, 0.12) !important; border: 1px solid rgba(255, 71, 87, 0.35) !important; border-radius: 50% !important; display: flex !important; align-items: center !important; justify-content: center !important; color: #ff4757 !important; box-shadow: 0 0 20px rgba(255, 71, 87, 0.25) !important;">
                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
                        <polyline points="16 17 21 12 16 7"></polyline>
                        <line x1="21" y1="12" x2="9" y2="12"></line>
                    </svg>
                </div>
                <h3 style="margin: 0 0 10px !important; color: #ffffff !important; font-size: 20px !important; font-weight: 700 !important; letter-spacing: -0.3px !important;">Exit Secure Exam Browser?</h3>
                <p style="margin: 0 0 26px !important; color: #94a3b8 !important; font-size: 13.5px !important; line-height: 1.55 !important;">
                    Exiting will immediately terminate your active examination session and forfeit unsubmitted answers. Are you sure you want to exit?
                </p>
                <div style="display: flex !important; gap: 14px !important; justify-content: center !important;">
                    <button id="cyber-exit-cancel-btn" type="button" style="flex: 1 !important; padding: 12px 18px !important; border-radius: 10px !important; background: rgba(255, 255, 255, 0.08) !important; border: 1px solid rgba(255, 255, 255, 0.15) !important; color: #e2e8f0 !important; font-size: 13.5px !important; font-weight: 600 !important; cursor: pointer !important; transition: all 0.2s ease !important;">Stay in Exam</button>
                    <button id="cyber-exit-confirm-btn" type="button" style="flex: 1 !important; padding: 12px 18px !important; border-radius: 10px !important; background: linear-gradient(135deg, #ef4444, #dc2626) !important; border: 1px solid #f87171 !important; color: #ffffff !important; font-size: 13.5px !important; font-weight: 600 !important; cursor: pointer !important; transition: all 0.2s ease !important; box-shadow: 0 4px 15px rgba(239, 68, 68, 0.4) !important;">Exit Application</button>
                </div>
            </div>
        \`;

        document.body.appendChild(overlay);

        const cancelBtn = overlay.querySelector('#cyber-exit-cancel-btn');
        const confirmBtn = overlay.querySelector('#cyber-exit-confirm-btn');

        cancelBtn.onmouseenter = () => { cancelBtn.style.background = 'rgba(255, 255, 255, 0.14)'; };
        cancelBtn.onmouseleave = () => { cancelBtn.style.background = 'rgba(255, 255, 255, 0.08)'; };

        confirmBtn.onmouseenter = () => { confirmBtn.style.transform = 'translateY(-1px)'; confirmBtn.style.boxShadow = '0 6px 20px rgba(239, 68, 68, 0.55)'; };
        confirmBtn.onmouseleave = () => { confirmBtn.style.transform = 'none'; confirmBtn.style.boxShadow = '0 4px 15px rgba(239, 68, 68, 0.4)'; };

        const closeModal = () => {
            document.removeEventListener('keydown', escHandler);
            if (overlay && overlay.parentNode) {
                overlay.remove();
            }
            console.log('__APP:CANCEL_EXIT__');
        };

        const escHandler = (e) => {
            if (e.key === 'Escape') {
                closeModal();
            }
        };
        document.addEventListener('keydown', escHandler);

        cancelBtn.onclick = closeModal;

        confirmBtn.onclick = () => {
            confirmBtn.disabled = true;
            confirmBtn.innerText = 'Exiting...';
            console.log('__APP:CONFIRM_EXIT__');
        };
    };
})();
`;

function promptExit() {
    showCyberExitModal();
}

function showCyberExitModal() {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    isExitingDialogActive = true;
    try {
        mainWindow.focus();
    } catch (e) {}

    mainWindow.webContents.executeJavaScript(`
        (function() {
            if (typeof window.__showCyberExitModal === 'function') {
                window.__showCyberExitModal();
            } else {
                ${CYBER_MODAL_SCRIPT}
                if (typeof window.__showCyberExitModal === 'function') {
                    window.__showCyberExitModal();
                }
            }
        })();
    `).catch((err) => {
        console.warn('Could not display cyber exit modal:', err);
        isExitingDialogActive = false;
    });
}

function showCyberUpdateModal(version) {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    isExitingDialogActive = true;
    try {
        mainWindow.focus();
    } catch (e) {}

    mainWindow.webContents.executeJavaScript(`
        (function() {
            if (document.getElementById('cyberonites-update-modal-overlay')) return;

            const overlay = document.createElement('div');
            overlay.id = 'cyberonites-update-modal-overlay';
            overlay.style.cssText = 'position: fixed !important; inset: 0 !important; width: 100vw !important; height: 100vh !important; background: rgba(4, 8, 16, 0.88) !important; backdrop-filter: blur(14px) !important; -webkit-backdrop-filter: blur(14px) !important; z-index: 2147483647 !important; display: flex !important; align-items: center !important; justify-content: center !important; animation: cyberExitFadeIn 0.25s ease-out !important; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Inter", sans-serif !important;';

            overlay.innerHTML = \`
                <div style="background: linear-gradient(145deg, #111827, #0b0f19) !important; border: 1.5px solid rgba(0, 210, 255, 0.45) !important; border-radius: 20px !important; padding: 36px 40px !important; max-width: 460px !important; width: 92% !important; text-align: center !important; box-shadow: 0 25px 60px rgba(0, 0, 0, 0.9), 0 0 35px rgba(0, 210, 255, 0.25) !important; animation: cyberExitScale 0.25s cubic-bezier(0.16, 1, 0.3, 1) !important;">
                    <div style="width: 60px !important; height: 60px !important; margin: 0 auto 18px !important; background: rgba(0, 210, 255, 0.12) !important; border: 1px solid rgba(0, 210, 255, 0.4) !important; border-radius: 50% !important; display: flex !important; align-items: center !important; justify-content: center !important; color: #00d2ff !important; box-shadow: 0 0 25px rgba(0, 210, 255, 0.3) !important;">
                        <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                            <polyline points="7 10 12 15 17 10"></polyline>
                            <line x1="12" y1="15" x2="12" y2="3"></line>
                        </svg>
                    </div>
                    <h3 style="margin: 0 0 10px !important; color: #ffffff !important; font-size: 21px !important; font-weight: 700 !important; letter-spacing: -0.3px !important;">Security Update Ready (v\${version})</h3>
                    <p style="margin: 0 0 26px !important; color: #94a3b8 !important; font-size: 13.5px !important; line-height: 1.6 !important;">
                        A mandatory security enhancement has been downloaded. Restart now to apply this patch and guarantee uniform proctoring compliance.
                    </p>
                    <div style="display: flex !important; gap: 14px !important; justify-content: center !important;">
                        <button id="cyber-update-restart-btn" type="button" style="flex: 1 !important; padding: 13px 20px !important; border-radius: 12px !important; background: linear-gradient(135deg, #00d2ff, #0077ff) !important; border: 1px solid #38bdf8 !important; color: #ffffff !important; font-size: 14px !important; font-weight: 700 !important; cursor: pointer !important; transition: all 0.2s ease !important; box-shadow: 0 4px 20px rgba(0, 210, 255, 0.4) !important;">Restart & Apply Update</button>
                    </div>
                </div>
            \`;

            document.body.appendChild(overlay);

            const restartBtn = overlay.querySelector('#cyber-update-restart-btn');
            restartBtn.onmouseenter = () => { restartBtn.style.transform = 'translateY(-1px)'; restartBtn.style.boxShadow = '0 6px 25px rgba(0, 210, 255, 0.55)'; };
            restartBtn.onmouseleave = () => { restartBtn.style.transform = 'none'; restartBtn.style.boxShadow = '0 4px 20px rgba(0, 210, 255, 0.4)'; };
            restartBtn.onclick = () => {
                restartBtn.disabled = true;
                restartBtn.innerText = 'Restarting & Updating...';
                console.log('__APP:RESTART_UPDATE__');
            };
        })();
    `).catch((err) => {
        console.warn('Could not display cyber update modal:', err);
    });
}

/**
 * Active Kiosk Lockout Enforcer:
 * Guarantees candidate cannot switch to other apps (Chrome, Discord, Snipping Tool) or escape to taskbar.
 */
let explorerCheckCounter = 0;
function startFocusEnforcer() {
    if (focusEnforcerInterval) clearInterval(focusEnforcerInterval);
    focusEnforcerInterval = setInterval(() => {
        if (isExitingDialogActive || !mainWindow || mainWindow.isDestroyed()) return;
        
        // Periodic check every 3 seconds (25 * 120ms) to ensure explorer shell remains suppressed
        explorerCheckCounter++;
        if (explorerCheckCounter % 25 === 0) {
            if (process.platform === 'win32' && isEnvironmentActive) {
                exec('taskkill /f /im explorer.exe /im ShellExperienceHost.exe /im StartMenuExperienceHost.exe', { windowsHide: true }, () => {});
            }
        }

        if (!mainWindow.isFocused()) {
            if (process.platform === 'win32') {
                // Instantly dismiss Windows 10/11 Task View or Virtual Desktop overlay if opened via 3/4-finger swipe
                exec('powershell -NoProfile -WindowStyle Hidden -Command "$w=New-Object -ComObject wscript.shell;$w.SendKeys(\'{ESC}\')"', { windowsHide: true }, () => {});
                exec('taskkill /f /im ScreenClippingHost.exe /im SnippingTool.exe', { windowsHide: true }, () => {});
            }
            clipboard.clear();
            if (mainWindow.isMinimized()) {
                mainWindow.restore();
            }
            mainWindow.setKiosk(true);
            mainWindow.setFullScreen(true);
            mainWindow.setAlwaysOnTop(false);
            mainWindow.setAlwaysOnTop(true, 'screen-saver');
            mainWindow.moveTop();
            mainWindow.show();
            mainWindow.focus();
        }
    }, 120); // Ultra-fast 120ms snap-back
}
let isLiveStreaming = false;
let liveStreamTimer = null;
let liveStreamWatcherInterval = null;

function setLiveStreaming(active) {
    if (active === isLiveStreaming) return;
    isLiveStreaming = active;
    if (isLiveStreaming) {
        runLiveStreamLoop();
    } else {
        if (liveStreamTimer) {
            clearTimeout(liveStreamTimer);
            liveStreamTimer = null;
        }
    }
}

async function runLiveStreamLoop() {
    if (!isLiveStreaming || !mainWindow || mainWindow.isDestroyed()) return;
    try {
        const image = await mainWindow.capturePage();
        if (image && !image.isEmpty()) {
            const size = image.getSize();
            const targetWidth = Math.min(size.width, 768);
            const resized = image.resize({ width: targetWidth });
            const base64Data = resized.toJPEG(45).toString('base64');

            await mainWindow.webContents.executeJavaScript(`
                if (typeof window.__sendStreamFrame === 'function') {
                    window.__sendStreamFrame(${JSON.stringify(base64Data)});
                }
            `);
        }
    } catch (err) {
        console.warn('Live frame capture error:', err);
    }

    if (isLiveStreaming) {
        // Stream at ~3 fps for smooth, zero-buffer real-time viewing
        liveStreamTimer = setTimeout(runLiveStreamLoop, 350);
    }
}

function startLiveStreamWatcher() {
    if (liveStreamWatcherInterval) clearInterval(liveStreamWatcherInterval);
    // Active safety check every 1s
    liveStreamWatcherInterval = setInterval(async () => {
        if (!mainWindow || mainWindow.isDestroyed()) return;
        try {
            const wantsStream = await mainWindow.webContents.executeJavaScript('Boolean(window.__wantsLiveStream)');
            if (wantsStream !== isLiveStreaming) {
                setLiveStreaming(wantsStream);
            }
        } catch (e) {}
    }, 1000);
}

function createWindow() {
    const primaryDisplay = screen.getPrimaryDisplay();
    const { x, y, width, height } = primaryDisplay.bounds;

    mainWindow = new BrowserWindow({
        x: x,
        y: y,
        width: width,
        height: height,
        frame: false,
        thickFrame: false,
        fullscreen: true,
        kiosk: true,
        alwaysOnTop: true,
        minimizable: false,
        maximizable: false,
        resizable: false,
        movable: false,
        skipTaskbar: true,
        autoHideMenuBar: true,
        backgroundColor: '#070b14',
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            devTools: false,
            pinchToZoom: false
        }
    });

    // Enforce 100% full screen coverage across primary display
    mainWindow.setBounds({ x, y, width, height });
    mainWindow.setKiosk(true);
    mainWindow.setFullScreen(true);

    // Enforce top-most screen-saver level on Windows to stay above Taskbar, Snipping Tool, and notifications
    try {
        mainWindow.setAlwaysOnTop(true, 'screen-saver');
    } catch (e) {
        mainWindow.setAlwaysOnTop(true);
    }

    // Pin window across ALL Virtual Desktops/Workspaces so 4-finger swipe cannot escape to another desktop
    try {
        mainWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
    } catch (e) {}

    // Hook Windows system commands to suppress minimize, task switching, and system menu
    if (process.platform === 'win32' && typeof mainWindow.hookWindowMessage === 'function') {
        mainWindow.hookWindowMessage(0x0112, (wParam) => {
            try {
                const cmd = wParam.readUInt32LE(0) & 0xFFF0;
                // 0xF020 = SC_MINIMIZE, 0xF040 = SC_NEXTWINDOW, 0xF050 = SC_PREVWINDOW, 0xF130 = SC_TASKLIST
                if ([0xF020, 0xF040, 0xF050, 0xF130].includes(cmd)) {
                    return true; // Suppress and consume message
                }
            } catch (err) {}
        });
    }

    // Content Protection disabled to allow navigator.mediaDevices.getDisplayMedia and desktopCapturer to capture active exam window instead of blank desktop
    try {
        mainWindow.setContentProtection(false);
    } catch (e) {}

    mainWindow.setMenuBarVisibility(false);

    // Instant zero-lag stream command and exit triggers from webpage console
    mainWindow.webContents.on('console-message', (event, ...args) => {
        const msg = String((event && event.message) || args[1] || args[0] || '').trim();
        if (msg.includes('__STREAM:START__')) {
            setLiveStreaming(true);
        } else if (msg.includes('__STREAM:STOP__')) {
            setLiveStreaming(false);
        } else if (msg.includes('__APP:MODAL_OPENED__') || msg.includes('__APP:PROMPT_EXIT__')) {
            isExitingDialogActive = true;
            if (msg.includes('__APP:PROMPT_EXIT__')) {
                showCyberExitModal();
            }
        } else if (msg.includes('__APP:CONFIRM_EXIT__')) {
            exitAppDirectly();
        } else if (msg.includes('__APP:CANCEL_EXIT__')) {
            isExitingDialogActive = false;
            if (mainWindow && !mainWindow.isDestroyed()) {
                mainWindow.focus();
            }
        } else if (msg.includes('__APP:RESTART_UPDATE__')) {
            try {
                autoUpdater.quitAndInstall();
            } catch (err) {
                console.warn('Failed to quit and install update:', err);
            }
        }
    });

    // Inject sleek, cyber-themed floating "Exit App" badge button and exit confirmation modal
    mainWindow.webContents.on('did-finish-load', () => {
        mainWindow.webContents.insertCSS(CYBER_MODAL_CSS);
        mainWindow.webContents.executeJavaScript(CYBER_MODAL_SCRIPT).catch(() => {});
    });

    // Set custom user agent with CyberonitesSecureBrowser identifier
    const defaultUA = mainWindow.webContents.getUserAgent();
    const APP_VERSION = app.getVersion() || '1.0.0';
    mainWindow.webContents.setUserAgent(`${defaultUA} CyberonitesSecureBrowser/${APP_VERSION}`);

    // Inject dynamic cryptographic attestation headers on all requests via Ed25519
    session.defaultSession.webRequest.onBeforeSendHeaders((details, callback) => {
        // Fast-path bypass for static resources (CSS, JS, Images, Fonts) to maximize performance
        if (['stylesheet', 'image', 'font'].includes(details.resourceType)) {
            return callback({ cancel: false });
        }

        try {
            const parsedUrl = new URL(details.url);
            const timestamp = Date.now().toString();
            const nonce = crypto.randomUUID ? crypto.randomUUID().replace(/-/g, '') : crypto.randomBytes(16).toString('hex');
            const method = (details.method || 'GET').toUpperCase();
            const pathname = parsedUrl.pathname;

            // Canonical message format: {timestamp}:{nonce}:{method}:{path}
            const messageToSign = `${timestamp}:${nonce}:${method}:${pathname}`;
            const signature = crypto.sign(null, Buffer.from(messageToSign, 'utf8'), clientPrivateKeyObj).toString('hex');

            details.requestHeaders['X-Secure-App-Timestamp'] = timestamp;
            details.requestHeaders['X-Secure-App-Nonce'] = nonce;
            details.requestHeaders['X-Secure-App-Signature'] = signature;
            details.requestHeaders['X-Secure-App-Public-Key'] = CLIENT_PUBLIC_KEY_HEX;
            details.requestHeaders['X-Secure-App-Version'] = APP_VERSION;
            // Legacy token header alias
            details.requestHeaders['X-Secure-App-Token'] = signature;
        } catch (err) {
            console.warn('[Attestation Header Error]:', err.message);
        }

        callback({ cancel: false, requestHeaders: details.requestHeaders });
    });

    // Explicitly grant media and screen capture permissions in Electron
    session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
        callback(true);
    });
    session.defaultSession.setPermissionCheckHandler((webContents, permission, requestingOrigin) => {
        return true;
    });

    // Support navigator.mediaDevices.getDisplayMedia for pre-flight screen sharing in Electron
    if (typeof session.defaultSession.setDisplayMediaRequestHandler === 'function') {
        session.defaultSession.setDisplayMediaRequestHandler((request, callback) => {
            desktopCapturer.getSources({ types: ['screen'] }).then((sources) => {
                if (sources && sources.length > 0) {
                    callback({ video: sources[0] });
                } else {
                    callback({});
                }
            }).catch((err) => {
                console.warn('Display media request error:', err);
                callback({});
            });
        });
    }

    // Block admin navigation inside Secure Exam Browser (allow student result page)
    mainWindow.webContents.on('will-navigate', (event, url) => {
        if (url.includes('/accounts/admin-login') || (url.includes('/dashboard/') && !url.includes('/dashboard/result/'))) {
            event.preventDefault();
            mainWindow.webContents.executeJavaScript(`
                if (typeof showToast === 'function') {
                    showToast('Admin controls are disabled inside the Secure Exam Browser.', 'warning');
                }
            `).catch(() => {});
        }
    });

    // Prevent touchpad/mouse gesture navigation (swipe left/right/up)
    mainWindow.on('swipe', (e) => {
        e.preventDefault();
    });

    // Prevent minimizing
    mainWindow.on('minimize', (e) => {
        e.preventDefault();
        mainWindow.restore();
        mainWindow.setKiosk(true);
        mainWindow.setFullScreen(true);
        mainWindow.setAlwaysOnTop(true, 'screen-saver');
        mainWindow.focus();
    });

    // Detect window blur (e.g. 3-finger swipe up to Task View or Alt+Tab attempt)
    mainWindow.on('blur', () => {
        // Kill Snipping Tool and dismiss Task View/Action Center overlays immediately
        if (process.platform === 'win32') {
            exec('powershell -NoProfile -WindowStyle Hidden -Command "$w=New-Object -ComObject wscript.shell;$w.SendKeys(\'{ESC}\')"', { windowsHide: true }, () => {});
            exec('taskkill /f /im ScreenClippingHost.exe /im SnippingTool.exe', { windowsHide: true }, () => {});
        }
        clipboard.clear();

        setImmediate(() => {
            if (mainWindow && !mainWindow.isDestroyed()) {
                if (mainWindow.isMinimized()) {
                    mainWindow.restore();
                }
                mainWindow.setKiosk(true);
                mainWindow.setFullScreen(true);
                mainWindow.setAlwaysOnTop(false);
                mainWindow.setAlwaysOnTop(true, 'screen-saver');
                mainWindow.moveTop();
                mainWindow.show();
                mainWindow.focus();
            }
        });

        reportNativeViolation('GESTURE_SWIPE', 'Task View or multi-finger gesture attempted');
    });

    // Disable browser shortcuts inside the window & block screenshot keys
    mainWindow.webContents.on('before-input-event', (event, input) => {
        const key = input.key.toLowerCase();
        const ctrl = input.control || input.meta;

        // Clean exit shortcuts (Alt+F4, Ctrl+Shift+Q, Ctrl+Q)
        if ((input.alt && key === 'f4') || (ctrl && input.shift && key === 'q') || (ctrl && key === 'q')) {
            event.preventDefault();
            promptExit();
            return;
        }

        // Block PrintScreen screenshot attempt
        if (key === 'printscreen') {
            event.preventDefault();
            if (process.platform === 'win32') {
                exec('taskkill /f /im ScreenClippingHost.exe /im SnippingTool.exe', { windowsHide: true }, () => {});
            }
            clipboard.clear();
            reportNativeViolation('KEY_VIOLATION', 'PrintScreen key pressed (Screenshot Blocked)');
            return;
        }

        // Block browser history navigation buttons
        if (key === 'browserback' || key === 'browserforward') {
            event.preventDefault();
        }
        if (input.alt && (key === 'arrowleft' || key === 'arrowright')) {
            event.preventDefault();
        }

        // Block DevTools (Ctrl+Shift+I, F12)
        if ((ctrl && input.shift && key === 'i') || key === 'f12') {
            event.preventDefault();
        }
        // Block Refresh (F5, Ctrl+R)
        if (key === 'f5' || (ctrl && key === 'r')) {
            event.preventDefault();
        }
        // Block Copy/Paste/Cut/Print/Save/ViewSource
        if (ctrl && ['c', 'v', 'x', 'a', 'p', 's', 'u'].includes(key)) {
            event.preventDefault();
        }
        // Block full screen toggles (F11, Esc)
        if (key === 'f11' || key === 'escape') {
            event.preventDefault();
        }
    });

    // Disable right-click context menu
    mainWindow.webContents.on('context-menu', (e) => {
        e.preventDefault();
    });

    // Handle load failure gracefully
    mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDescription, validatedURL) => {
        if (errorCode === -3) return; // Ignore aborted requests
        dialog.showMessageBox(mainWindow, {
            type: 'error',
            title: 'Connection Error',
            message: `Could not load examination portal:\n${errorDescription} (${errorCode})\n\nURL: ${validatedURL}\n\nPlease check your internet connection or server availability.`,
            buttons: ['Retry', 'Exit'],
            defaultId: 0,
        }).then(({ response }) => {
            if (response === 0) {
                mainWindow.loadURL(EXAM_URL);
            } else {
                app.exit(1);
            }
        });
    });

    // Load exam portal
    mainWindow.loadURL(EXAM_URL);

    // Prevent accidental closing - prompt clean exit
    mainWindow.on('close', (e) => {
        e.preventDefault();
        promptExit();
    });
}

app.whenReady().then(async () => {
    // Initial hardware security scan (VM, RDP, Multi-Monitor)
    // NOTE: Background processes are monitored passively so legitimate OEM/gaming processes (e.g. HP OMEN) are never blocked on launch.
    const initialViolation = await checkHardwareViolations();
    if (initialViolation) {
        dialog.showErrorBox(
            'Examination Security Requirement Failed',
            `The Secure Exam Browser cannot launch due to a hardware security violation:\n\n• ${initialViolation}\n\nRequirements:\n1. Must run on a physical laptop or PC (Virtual Machines are forbidden).\n2. Remote Desktop (RDP) sessions are forbidden.\n3. Only single-monitor displays are permitted (disconnect external HDMI/monitors).`
        );
        app.exit(0);
        return;
    }

    createWindow();

    if (customConfig.isolate_environment !== false) {
        enterSecureKioskEnvironment();
    }

    // Listen for dynamic external monitor connections during the examination
    try {
        screen.on('display-added', () => {
            reportNativeViolation('VM_DETECTED', 'External monitor or HDMI display dynamically connected');
            dialog.showErrorBox(
                'Security Violation Detected',
                'An external monitor or display was connected during the examination.\n\nPlease disconnect all external displays immediately to avoid exam invalidation.'
            );
        });
    } catch (e) {}

    // Register safe global shortcuts
    try {
        const gestureAndSwitchShortcuts = [
            'Alt+Tab',
            'CommandOrControl+Tab',
            'CommandOrControl+Escape',
            'Alt+Escape',
            'Super+Tab',
            'Super+D',
            'Super+A',
            'Super+S',
            'Super+Down',
            'Super+Up',
            'Super+M',
            'Super+Shift+M',
            'Control+Super+Left',
            'Control+Super+Right',
            'Control+Super+D',
            'Control+Super+F4',
            'Alt+Space'
        ];

        for (const sc of gestureAndSwitchShortcuts) {
            try {
                globalShortcut.register(sc, () => {
                    if (mainWindow && !mainWindow.isDestroyed()) {
                        mainWindow.setAlwaysOnTop(true, 'screen-saver');
                        mainWindow.moveTop();
                        mainWindow.focus();
                    }
                });
            } catch (e) {}
        }

        // Allow Alt+F4, Ctrl+Shift+Q, and Ctrl+Q to prompt custom Cyber exit modal
        globalShortcut.register('Alt+F4', () => {
            showCyberExitModal();
        });
        globalShortcut.register('CommandOrControl+Shift+Q', () => {
            showCyberExitModal();
        });
        globalShortcut.register('CommandOrControl+Q', () => {
            showCyberExitModal();
        });

        // Intercept Windows Snipping Tool (Win+Shift+S / Ctrl+Shift+S)
        globalShortcut.register('CommandOrControl+Shift+S', () => {
            if (process.platform === 'win32') {
                exec('taskkill /f /im ScreenClippingHost.exe /im SnippingTool.exe', { windowsHide: true }, () => {});
            }
            clipboard.clear();
            if (mainWindow && !mainWindow.isDestroyed()) {
                mainWindow.setAlwaysOnTop(false);
                mainWindow.setAlwaysOnTop(true, 'screen-saver');
                mainWindow.moveTop();
                mainWindow.focus();
                reportNativeViolation('KEY_VIOLATION', 'Snipping Tool shortcut intercepted');
            }
        });

        // Intercept PrintScreen
        globalShortcut.register('PrintScreen', () => {
            if (process.platform === 'win32') {
                exec('taskkill /f /im ScreenClippingHost.exe /im SnippingTool.exe', { windowsHide: true }, () => {});
            }
            clipboard.clear();
            if (mainWindow && !mainWindow.isDestroyed()) {
                mainWindow.setAlwaysOnTop(false);
                mainWindow.setAlwaysOnTop(true, 'screen-saver');
                mainWindow.moveTop();
                mainWindow.focus();
                reportNativeViolation('KEY_VIOLATION', 'Global PrintScreen hotkey intercepted');
            }
        });

        // macOS Specific Screenshot and Shortcut Interceptions
        globalShortcut.register('CommandOrControl+Shift+3', () => {
            clipboard.clear();
            reportNativeViolation('KEY_VIOLATION', 'macOS Full Screenshot attempt (Cmd+Shift+3)');
        });
        globalShortcut.register('CommandOrControl+Shift+4', () => {
            clipboard.clear();
            reportNativeViolation('KEY_VIOLATION', 'macOS Selection Screenshot attempt (Cmd+Shift+4)');
        });
        globalShortcut.register('CommandOrControl+Shift+5', () => {
            clipboard.clear();
            reportNativeViolation('KEY_VIOLATION', 'macOS Screen Recording toolbar attempt (Cmd+Shift+5)');
        });
        globalShortcut.register('CommandOrControl+Space', () => {
            reportNativeViolation('KEY_VIOLATION', 'macOS Spotlight Search attempted');
        });
        globalShortcut.register('CommandOrControl+H', () => {}); // Block macOS Hide Window
        globalShortcut.register('CommandOrControl+M', () => {}); // Block macOS Minimize Window
        globalShortcut.register('CommandOrControl+Alt+Escape', () => {}); // Block macOS Force Quit prompt
    } catch (e) {
        console.warn('Could not register system shortcuts:', e);
    }

    startMonitoring();
    startLiveStreamWatcher();
    startFocusEnforcer();
    setupAutoUpdater();

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) {
            createWindow();
        }
    });
});

function setupAutoUpdater() {
    if (!app.isPackaged && process.env.NODE_ENV !== 'production') {
        console.log('[AutoUpdater] Development mode: skipping GitHub update checks.');
        return;
    }

    try {
        autoUpdater.autoDownload = true;
        autoUpdater.autoInstallOnAppQuit = true;

        autoUpdater.on('checking-for-update', () => {
            console.log('[AutoUpdater] Checking for updates from GitHub Releases...');
        });

        autoUpdater.on('update-available', (info) => {
            console.log(`[AutoUpdater] Update available: v${info.version}`);
            if (mainWindow && !mainWindow.isDestroyed()) {
                mainWindow.webContents.executeJavaScript(`
                    if (typeof window.showToast === 'function') {
                        window.showToast('Security update v${info.version} downloading in background...', 'info');
                    }
                `).catch(() => {});
            }
        });

        autoUpdater.on('update-not-available', () => {
            console.log(`[AutoUpdater] App is up to date (v${app.getVersion()}).`);
        });

        autoUpdater.on('error', (err) => {
            console.warn('[AutoUpdater] Update check error:', err ? err.message : 'Unknown');
        });

        autoUpdater.on('update-downloaded', (info) => {
            console.log(`[AutoUpdater] Update v${info.version} downloaded successfully.`);
            showCyberUpdateModal(info.version);
        });

        // Initial check after 4 seconds to allow page rendering
        setTimeout(() => {
            autoUpdater.checkForUpdates().catch((err) => {
                console.warn('[AutoUpdater] Initial check error:', err.message);
            });
        }, 4000);

        // Periodically check every 30 minutes
        setInterval(() => {
            autoUpdater.checkForUpdates().catch(() => {});
        }, 30 * 60 * 1000);
    } catch (e) {
        console.warn('[AutoUpdater] Setup error:', e);
    }
}

app.on('will-quit', () => {
    leaveSecureKioskEnvironment();
    if (monitoringInterval) clearInterval(monitoringInterval);
    if (liveStreamWatcherInterval) clearInterval(liveStreamWatcherInterval);
    if (liveStreamTimer) clearTimeout(liveStreamTimer);
    if (focusEnforcerInterval) clearInterval(focusEnforcerInterval);
    globalShortcut.unregisterAll();
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit();
    }
});
