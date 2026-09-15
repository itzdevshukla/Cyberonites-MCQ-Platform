const { app, BrowserWindow, globalShortcut, session, dialog, clipboard, desktopCapturer, net } = require('electron');
const { exec } = require('child_process');
const crypto = require('crypto');
const path = require('path');
const fs = require('fs');

// Disable touchpad overscroll history navigation (swiping left/right to go back/forward)
app.commandLine.appendSwitch('disable-features', 'TouchpadOverscrollHistoryNavigation,OverscrollHistoryNavigation');
app.commandLine.appendSwitch('disable-pinch');

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

    // Web Browsers
    'chrome': 'Google Chrome',
    'msedge': 'Microsoft Edge',
    'brave': 'Brave Browser',
    'firefox': 'Mozilla Firefox',
    'opera': 'Opera Browser',
    'opera_gx': 'Opera GX',
    'vivaldi': 'Vivaldi Browser',
    'tor': 'Tor Browser',
    'torbrowser': 'Tor Browser',
    'safari': 'Apple Safari',

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

    // Virtual Machines
    'virtualbox': 'Oracle VirtualBox',
    'virtualboxvm': 'VirtualBox VM',
    'vboxmanage': 'VirtualBox Manager',
    'vboxsvc': 'VirtualBox Service',
    'vmware': 'VMware Workstation',
    'vmware-vmx': 'VMware Virtual Machine',
    'qemu-system-x86_64': 'QEMU Virtual Machine',
    'qemu-system-i386': 'QEMU Virtual Machine',
    'qemu': 'QEMU Emulator'
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
 * Check if the current system is running in a virtual machine environment.
 */
function checkVirtualMachine() {
    return new Promise((resolve) => {
        if (process.platform === 'win32') {
            exec('reg query "HKLM\\SYSTEM\\CurrentControlSet\\Control\\SystemInformation"', { windowsHide: true }, (err, stdout) => {
                if (err || !stdout) return resolve(false);
                const text = stdout.toLowerCase();
                const vmSignatures = ['virtualbox', 'vmware', 'qemu', 'xen', 'parallels'];
                for (const sig of vmSignatures) {
                    if (text.includes(sig)) return resolve(sig.toUpperCase());
                }
                resolve(false);
            });
        } else {
            resolve(false);
        }
    });
}

/**
 * Scan for any violations (blacklisted processes or VM environment).
 */
async function checkSecurityViolations(checkVM = false) {
    try {
        const processes = await getRunningProcesses();

        for (const raw of processes) {
            if (raw.includes('secure-app') || raw.includes('electron') || raw.includes('cyberonites')) {
                continue;
            }
            if (raw === 'msedgewebview2.exe') {
                continue;
            }

            const base = raw.replace(/\.exe$/, '').trim();
            if (PROHIBITED_MAP[base]) {
                const friendly = PROHIBITED_MAP[base];
                return `${friendly} (${raw})`;
            }
        }

        if (checkVM) {
            const vmType = await checkVirtualMachine();
            if (vmType) {
                return `Virtual Machine Environment Detected (${vmType})`;
            }
        }
    } catch (e) {
        console.error('Error during security check:', e);
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
function startMonitoring() {
    if (monitoringInterval) clearInterval(monitoringInterval);
    monitoringInterval = setInterval(async () => {
        const violation = await checkSecurityViolations(false);
        if (violation && mainWindow && !mainWindow.isDestroyed()) {
            clearInterval(monitoringInterval);
            if (focusEnforcerInterval) clearInterval(focusEnforcerInterval);

            console.warn(`[Security Alert] Prohibited application detected: ${violation}`);

            // 1. Authoritative out-of-band report directly from Electron Main process
            // AWAIT server delivery confirmation BEFORE terminating the app!
            try {
                await Promise.race([
                    reportNativeViolation('PROHIBITED_PROCESS', violation),
                    new Promise(resolve => setTimeout(resolve, 3500))
                ]);
            } catch (e) {
                console.error('[Security] Error awaiting violation delivery:', e);
            }

            // 2. Show native dialog to student
            dialog.showErrorBox(
                'Security Violation Detected',
                `Prohibited application detected running in the background:\n\n• ${violation}\n\nFor examination integrity, this security incident has been recorded on the server and the Secure Exam Browser will now close.\n\nPlease terminate the prohibited application before attempting to re-enter.`
            );

            // 3. Clean exit
            exitAppDirectly();
        }
    }, 6000);
}

let isExitingDialogActive = false;

function exitAppDirectly() {
    if (focusEnforcerInterval) clearInterval(focusEnforcerInterval);
    if (monitoringInterval) clearInterval(monitoringInterval);
    if (typeof snapshotInterval !== 'undefined' && snapshotInterval) clearInterval(snapshotInterval);
    if (liveStreamTimer) clearTimeout(liveStreamTimer);
    if (liveStreamWatcherInterval) clearInterval(liveStreamWatcherInterval);
    app.exit(0);
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
#cyberonites-exit-kiosk-btn {
    position: fixed !important;
    top: 13px !important;
    right: 20px !important;
    z-index: 2147483640 !important;
    background: rgba(13, 17, 23, 0.88) !important;
    backdrop-filter: blur(12px) !important;
    -webkit-backdrop-filter: blur(12px) !important;
    color: #ff6b81 !important;
    border: 1px solid rgba(255, 71, 87, 0.4) !important;
    border-radius: 20px !important;
    padding: 6px 15px !important;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Inter", sans-serif !important;
    font-size: 11px !important;
    font-weight: 600 !important;
    letter-spacing: 0.6px !important;
    text-transform: uppercase !important;
    cursor: pointer !important;
    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.5), 0 0 10px rgba(255, 71, 87, 0.2) !important;
    transition: all 0.25s ease !important;
    display: flex !important;
    align-items: center !important;
    gap: 7px !important;
    user-select: none !important;
}
#cyberonites-exit-kiosk-btn:hover {
    background: rgba(255, 71, 87, 0.2) !important;
    border-color: #ff4757 !important;
    color: #ffffff !important;
    box-shadow: 0 6px 20px rgba(255, 71, 87, 0.45) !important;
    transform: translateY(-1px) !important;
}
#cyberonites-exit-kiosk-btn .exit-dot {
    width: 7px !important;
    height: 7px !important;
    border-radius: 50% !important;
    background: #ff4757 !important;
    box-shadow: 0 0 6px #ff4757 !important;
    display: inline-block !important;
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

    if (!document.getElementById('cyberonites-exit-kiosk-btn')) {
        const btn = document.createElement('button');
        btn.id = 'cyberonites-exit-kiosk-btn';
        btn.innerHTML = '<span class="exit-dot"></span><span>Exit App</span>';
        btn.title = 'Safely exit the Secure Exam Browser (or press Alt+F4 / Ctrl+Q)';
        btn.onclick = () => {
            if (typeof window.__showCyberExitModal === 'function') {
                window.__showCyberExitModal();
            } else {
                console.log('__APP:PROMPT_EXIT__');
            }
        };
        document.body.appendChild(btn);
    }
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

/**
 * Active Kiosk Lockout Enforcer:
 * Guarantees candidate cannot switch to other apps (Chrome, Discord, Snipping Tool) or escape to taskbar.
 */
function startFocusEnforcer() {
    if (focusEnforcerInterval) clearInterval(focusEnforcerInterval);
    focusEnforcerInterval = setInterval(() => {
        if (isExitingDialogActive || !mainWindow || mainWindow.isDestroyed()) return;
        if (!mainWindow.isFocused()) {
            if (process.platform === 'win32') {
                exec('taskkill /f /im ScreenClippingHost.exe /im SnippingTool.exe', { windowsHide: true }, () => {});
            }
            clipboard.clear();
            mainWindow.setAlwaysOnTop(false);
            mainWindow.setAlwaysOnTop(true, 'screen-saver');
            mainWindow.moveTop();
            mainWindow.restore();
            mainWindow.show();
            mainWindow.focus();
        }
    }, 600);
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
    mainWindow = new BrowserWindow({
        width: 1280,
        height: 800,
        fullscreen: true,
        kiosk: true,
        alwaysOnTop: true,
        minimizable: false,
        maximizable: false,
        autoHideMenuBar: true,
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            devTools: false,
            pinchToZoom: false
        }
    });

    // Enforce top-most screen-saver level on Windows to stay above Taskbar, Snipping Tool, and notifications
    try {
        mainWindow.setAlwaysOnTop(true, 'screen-saver');
    } catch (e) {
        mainWindow.setAlwaysOnTop(true);
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
        }
    });

    // Inject sleek, cyber-themed floating "Exit App" badge button and exit confirmation modal
    mainWindow.webContents.on('did-finish-load', () => {
        mainWindow.webContents.insertCSS(CYBER_MODAL_CSS);
        mainWindow.webContents.executeJavaScript(CYBER_MODAL_SCRIPT).catch(() => {});
    });

    // Set custom user agent with CyberonitesSecureBrowser identifier
    const defaultUA = mainWindow.webContents.getUserAgent();
    mainWindow.webContents.setUserAgent(`${defaultUA} CyberonitesSecureBrowser/1.0`);

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
        mainWindow.setAlwaysOnTop(true, 'screen-saver');
        mainWindow.focus();
    });

    // Detect window blur (e.g. 3-finger swipe up to Task View or Alt+Tab attempt)
    mainWindow.on('blur', () => {
        // Kill Snipping Tool and screen capture hosts immediately
        if (process.platform === 'win32') {
            exec('taskkill /f /im ScreenClippingHost.exe /im SnippingTool.exe', { windowsHide: true }, () => {});
        }
        clipboard.clear();

        setImmediate(() => {
            if (mainWindow && !mainWindow.isDestroyed()) {
                mainWindow.setAlwaysOnTop(false);
                mainWindow.setAlwaysOnTop(true, 'screen-saver');
                mainWindow.moveTop();
                mainWindow.restore();
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
    // Initial violation check before opening window
    const initialViolation = await checkSecurityViolations(true);
    if (initialViolation) {
        dialog.showErrorBox(
            'Security Warning',
            `Prohibited application detected running:\n\n• ${initialViolation}\n\nPlease close this application before launching the Secure Exam Browser.`
        );
        app.exit(0);
        return;
    }

    createWindow();

    // Register safe global shortcuts
    try {
        globalShortcut.register('Alt+Tab', () => {});
        globalShortcut.register('CommandOrControl+Tab', () => {});
        globalShortcut.register('CommandOrControl+Escape', () => {});
        globalShortcut.register('Alt+Escape', () => {});

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
    } catch (e) {
        console.warn('Could not register system shortcuts:', e);
    }

    startMonitoring();
    startLiveStreamWatcher();
    startFocusEnforcer();

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) {
            createWindow();
        }
    });
});

app.on('will-quit', () => {
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
