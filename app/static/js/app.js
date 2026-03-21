// ReqSysAI - Main JavaScript
document.addEventListener('DOMContentLoaded', function() {
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
var _toastEl = null;
function showToast(msg, type) {
    type = type || 'info';
    if (!_toastEl) {
        _toastEl = document.createElement('div');
        _toastEl.className = 'position-fixed bottom-0 end-0 p-3';
        _toastEl.style.zIndex = '9999';
        _toastEl.innerHTML = '<div class="toast align-items-center border-0 show" role="alert">'
            + '<div class="d-flex"><div class="toast-body" id="_toastMsg"></div>'
            + '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div></div>';
        document.body.appendChild(_toastEl);
    }
    var toast = _toastEl.querySelector('.toast');
    toast.className = 'toast align-items-center border-0 show text-bg-' + type;
    document.getElementById('_toastMsg').textContent = msg;
    _toastEl.style.display = 'block';
    setTimeout(function() { _toastEl.style.display = 'none'; }, 3000);
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
            return {ok: false, msg: 'HTTP ' + r.status};
        }
        return r.json().catch(function() { return {ok: false, msg: '响应解析失败'}; });
    });
}
