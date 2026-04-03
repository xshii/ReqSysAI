// ReqSysAI - Main JavaScript

document.addEventListener('DOMContentLoaded', function() {
    // Global tooltip init: delay=0, no animation for instant display
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function(el) {
        new bootstrap.Tooltip(el, {delay: {show: 0, hide: 0}, animation: false});
    });
    // Also intercept dynamically created tooltips
    var _origTooltip = bootstrap.Tooltip;
    bootstrap.Tooltip = function(el, opts) {
        opts = opts || {};
        if (!opts.delay) opts.delay = {show: 0, hide: 0};
        if (opts.animation === undefined) opts.animation = false;
        return new _origTooltip(el, opts);
    };
    bootstrap.Tooltip.prototype = _origTooltip.prototype;
    bootstrap.Tooltip.getInstance = _origTooltip.getInstance;
    bootstrap.Tooltip.getOrCreateInstance = _origTooltip.getOrCreateInstance;
    bootstrap.Tooltip.Default = _origTooltip.Default;
    bootstrap.Tooltip.NAME = _origTooltip.NAME;

    // File upload loading overlay with progress bar and close button
    document.querySelectorAll('form[enctype="multipart/form-data"], form').forEach(function(form) {
        var fileInput = form.querySelector('input[type="file"]');
        if (!fileInput) return;
        form.addEventListener('submit', function() {
            if (!fileInput.value) return;
            var overlay = document.createElement('div');
            overlay.id = '_uploadOverlay';
            overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(255,255,255,.8);display:flex;align-items:center;justify-content:center;';
            overlay.innerHTML =
                '<div class="text-center" style="min-width:200px;">'
                + '<div class="spinner-border text-primary mb-2"></div>'
                + '<div class="small text-muted mb-2">上传中...</div>'
                + '<div class="progress mb-2" style="height:6px;"><div class="progress-bar progress-bar-striped progress-bar-animated" id="_uploadBar" style="width:0%;"></div></div>'
                + '<div class="small text-muted mb-2" id="_uploadTimer">0s</div>'
                + '<button class="btn btn-sm btn-outline-secondary" onclick="this.closest(\'#_uploadOverlay\').remove()"><i class="bi bi-x-lg"></i> 关闭</button>'
                + '</div>';
            document.body.appendChild(overlay);
            // Simulate progress + timer
            var start = Date.now(), pct = 0;
            var bar = overlay.querySelector('#_uploadBar');
            var timer = overlay.querySelector('#_uploadTimer');
            var iv = setInterval(function() {
                var sec = Math.round((Date.now() - start) / 1000);
                timer.textContent = sec + 's';
                if (pct < 90) { pct += Math.random() * 15; bar.style.width = Math.min(pct, 90) + '%'; }
            }, 500);
            // Auto-close after 30s as safety net
            setTimeout(function() {
                clearInterval(iv);
                var el = document.getElementById('_uploadOverlay');
                if (el) { el.querySelector('.small').textContent = '超时，请刷新页面'; }
            }, 30000);
        });
    });

    // Auto-dismiss alerts after 5 seconds
    var alerts = document.querySelectorAll('.alert-dismissible');
    alerts.forEach(function(alert) {
        setTimeout(function() {
            var bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            bsAlert.close();
        }, 5000);
    });
});

// ---- Global Toast utility ----
var _toastEl = null, _toastTimer = null;
function showToast(msg, type) {
    type = type || 'info';
    if (!_toastEl) {
        _toastEl = document.createElement('div');
        _toastEl.className = 'position-fixed bottom-0 end-0 p-3';
        _toastEl.style.zIndex = '9999';
        _toastEl.innerHTML = '<div class="toast align-items-center border-0 show" role="alert">'
            + '<div class="d-flex"><div class="toast-body" id="_toastMsg"></div>'
            + '<button type="button" class="btn-close btn-close-white me-2 m-auto" onclick="hideToast()"></button></div></div>';
        document.body.appendChild(_toastEl);
    }
    var toast = _toastEl.querySelector('.toast');
    toast.className = 'toast align-items-center border-0 show text-bg-' + type;
    document.getElementById('_toastMsg').textContent = msg;
    _toastEl.style.display = 'block';
    clearTimeout(_toastTimer);
    var delay = (type === 'danger' || type === 'warning') ? 5000 : 3000;
    _toastTimer = setTimeout(hideToast, delay);
}
function hideToast() { if (_toastEl) _toastEl.style.display = 'none'; }

// ---- Image lightbox ----
document.addEventListener('click', function(e) {
    var img = e.target.closest('.img-lightbox');
    if (img) {
        var src = img.dataset.src || img.src;
        document.getElementById('lightboxImg').src = src;
        new bootstrap.Modal(document.getElementById('imgLightbox')).show();
    }
});

// ---- User picker component ----
function initUserPicker(wrap) {
    if (wrap._pickerInit) return; // avoid double init
    wrap._pickerInit = true;
    var input = wrap.querySelector('.user-picker-input');
    var hidden = wrap.querySelector('.user-picker-val');
    var list = wrap.querySelector('.user-picker-list');
    var mode = input.dataset.mode || 'id';

    input.addEventListener('focus', function() { filter(); list.style.display = 'block'; });
    input.addEventListener('input', function() {
        filter();
        if (mode === 'text' || mode === 'manager') hidden.value = input.value.trim();
        else hidden.value = '';
    });
    input.addEventListener('blur', function() {
        setTimeout(function() { list.style.display = 'none'; }, 200);
        if ((mode === 'text' || mode === 'manager') && input.value.trim()) hidden.value = input.value.trim();
    });
    input.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            if (input.closest('#applyModal')) return;
            var first = list.querySelector('.user-picker-opt:not([style*="none"])');
            if (first) selectOpt(first);
        }
    });

    function filter() {
        var q = input.value.toLowerCase();
        list.querySelectorAll('.user-picker-opt').forEach(function(o) {
            var name = o.dataset.name.toLowerCase();
            var py = (o.dataset.pinyin || '').toLowerCase();
            var eid = (o.dataset.eid || '').toLowerCase();
            o.style.display = (name.includes(q) || py.includes(q) || eid.includes(q)) ? '' : 'none';
        });
        list.style.display = 'block';
    }

    function selectOpt(o) {
        if (mode === 'manager') {
            var val = o.dataset.name + ' ' + o.dataset.eid;
            input.value = val;
            hidden.value = val;
        } else {
            input.value = o.dataset.name;
            hidden.value = mode === 'id' ? o.dataset.id : o.dataset.name;
        }
        list.style.display = 'none';
    }

    // Use event delegation on list so dynamically added options work
    list.addEventListener('mousedown', function(e) {
        var o = e.target.closest('.user-picker-opt');
        if (!o) return;
        e.preventDefault();
        selectOpt(o);
    });
}
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.user-picker-wrap').forEach(initUserPicker);
});

// ---- Date picker: close on calendar select (not keyboard) ----
document.addEventListener('change', function(e) {
    if (e.target.type === 'date' && !e.target._keyActive) e.target.blur();
});
document.addEventListener('keydown', function(e) {
    if (e.target.type === 'date') {
        e.target._keyActive = true;
        clearTimeout(e.target._keyTimer);
        e.target._keyTimer = setTimeout(function() { e.target._keyActive = false; }, 800);
    }
});

// ---- Clear native tooltips before DOM removal ----
(function() {
    var origRemove = Element.prototype.remove;
    Element.prototype.remove = function() {
        this.removeAttribute('title');
        this.querySelectorAll('[title]').forEach(function(el) { el.removeAttribute('title'); });
        return origRemove.call(this);
    };
})();

// ---- AI button loading state with timer ----
// Submits the form via fetch so the page stays alive and the timer keeps ticking.
// On success the page reloads to show results; on error the button resets.
function aiLoading(btn, loadingText) {
    var origHtml = btn.innerHTML;
    var startTime = Date.now();
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> <i class="bi bi-robot"></i> ' + (loadingText || '生成中') + ' <span class="ai-timer">0s</span>';
    var timerEl = btn.querySelector('.ai-timer');
    var interval = setInterval(function() {
        var sec = Math.round((Date.now() - startTime) / 1000);
        if (timerEl) timerEl.textContent = sec + 's';
    }, 1000);
    return {
        stop: function() {
            clearInterval(interval);
            btn.disabled = false;
            btn.innerHTML = origHtml;
        }
    };
}

// Bind AI generate forms: submit via fetch to keep timer alive, then navigate.
function aiBindForm(form, btn, loadingText) {
    form.addEventListener('submit', function(e) {
        e.preventDefault();
        var ctrl = aiLoading(btn, loadingText);
        var action = form.action || window.location.href;
        fetch(action, {
            method: 'POST',
            body: new FormData(form),
            redirect: 'follow',
        }).then(function(resp) {
            // Navigate to final URL (handles both redirect and same-page reload)
            window.location.href = resp.url;
        }).catch(function() {
            ctrl.stop();
        });
    });
}

// ---- Clipboard copy with visual feedback ----
function copyWithFeedback(text, btn, richHtml) {
    function onSuccess() {
        if (btn) {
            var icon = btn.querySelector('i');
            if (icon) { var orig = icon.className; icon.className = 'bi bi-check-lg text-success'; setTimeout(function() { icon.className = orig; }, 1500); }
        }
        showToast('已复制', 'success');
    }
    function fallback() {
        var ta = document.createElement('textarea');
        ta.value = text; ta.style.cssText = 'position:fixed;opacity:0';
        document.body.appendChild(ta); ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        onSuccess();
    }
    if (richHtml && navigator.clipboard && navigator.clipboard.write) {
        navigator.clipboard.write([new ClipboardItem({
            'text/html': new Blob([richHtml], {type: 'text/html'}),
            'text/plain': new Blob([text], {type: 'text/plain'})
        })]).then(onSuccess).catch(fallback);
    } else if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(onSuccess).catch(fallback);
    } else {
        fallback();
    }
}

// ---- AJAX helper for JSON POST ----
function apiPost(url, data) {
    var csrfMeta = document.querySelector('meta[name="csrf-token"]');
    var token = csrfMeta ? csrfMeta.content : '';
    return fetch(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': token},
        body: JSON.stringify(data || {})
    }).then(function(r) {
        if (!r.ok) {
            console.error('API error:', r.status, url);
            showToast('操作失败 (HTTP ' + r.status + ')', 'danger');
            return {ok: false, msg: 'HTTP ' + r.status};
        }
        return r.json().catch(function() {
            showToast('响应解析失败', 'danger');
            return {ok: false, msg: '响应解析失败'};
        });
    }).catch(function(err) {
        console.error('Network error:', err);
        showToast('网络连接失败，请检查网络', 'danger');
        return {ok: false, msg: '网络错误'};
    });
}

// ---- Button loading helper (防重复点击) ----
function btnLoading(btn, text) {
    var orig = btn.innerHTML;
    var origDisabled = btn.disabled;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> ' + (text || '处理中...');
    return { stop: function() { btn.disabled = origDisabled; btn.innerHTML = orig; } };
}

// ---- Confirm action modal ----
var _confirmCallback = null;
function confirmAction(msg, callback) {
    _confirmCallback = callback;
    document.getElementById('confirmActionBody').innerHTML = msg;
    new bootstrap.Modal(document.getElementById('confirmActionModal')).show();
}
function _doConfirmAction() {
    bootstrap.Modal.getInstance(document.getElementById('confirmActionModal')).hide();
    if (_confirmCallback) { _confirmCallback(); _confirmCallback = null; }
}

// ---- Email settings: load/save from DB instead of localStorage ----
// DB stores *extra* recipients added by user; defaults are auto-computed.
// Settings UI shows only extras; EML export merges defaults + extras (dedup, managers first).
function _splitEids(s) {
    return (s || '').split(/[;,；，]/).map(function(e) { return e.trim(); }).filter(Boolean);
}
function _mergeEids(base, extra) {
    var arr = _splitEids(base);
    var seen = {};
    arr.forEach(function(e) { seen[e] = true; });
    _splitEids(extra).forEach(function(e) {
        if (!seen[e]) { arr.push(e); seen[e] = true; }
    });
    return arr.join(';');
}

// Global store for auto-computed defaults (per page)
var _emlDefaults = {to: '', cc: ''};

function loadEmailSettings(entityType, entityId, defaults, callback) {
    _emlDefaults = {to: defaults.to || '', cc: defaults.cc || ''};
    fetch('/api/email-settings/' + entityType + '/' + entityId)
    .then(function(r) { return r.json(); })
    .then(function(d) {
        // Show only extras in settings UI, not auto-computed defaults
        callback({
            subject: d.subject || defaults.subject || '',
            to: d.to || '',
            cc: d.cc || ''
        });
    })
    .catch(function() { callback({subject: defaults.subject || '', to: '', cc: ''}); });
}
function saveEmailSettings(entityType, entityId, subject, to, cc) {
    apiPost('/api/email-settings/' + entityType + '/' + entityId, {subject: subject, to: to, cc: cc});
}
// Call this at EML export time to get merged To/Cc (defaults + extras, dedup, defaults first)
function getMergedRecipients(extraTo, extraCc) {
    return {
        to: _mergeEids(_emlDefaults.to, extraTo),
        cc: _mergeEids(_emlDefaults.cc, extraCc)
    };
}

