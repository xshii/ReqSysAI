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
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.user-picker-wrap').forEach(function(wrap) {
        var input = wrap.querySelector('.user-picker-input');
        var hidden = wrap.querySelector('.user-picker-val');
        var list = wrap.querySelector('.user-picker-list');
        var mode = input.dataset.mode || 'id'; // 'id' or 'text'

        input.addEventListener('focus', function() { filter(); list.style.display = 'block'; });
        input.addEventListener('input', function() {
            filter();
            if (mode === 'text') hidden.value = input.value.trim();
            else hidden.value = ''; // Clear selection until picked
        });
        input.addEventListener('blur', function() {
            setTimeout(function() { list.style.display = 'none'; }, 200);
            // text mode: keep typed value
            if (mode === 'text' && input.value.trim()) hidden.value = input.value.trim();
        });
        input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
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
            input.value = o.dataset.name;
            hidden.value = mode === 'id' ? o.dataset.id : o.dataset.name;
            list.style.display = 'none';
        }

        list.querySelectorAll('.user-picker-opt').forEach(function(o) {
            o.addEventListener('mousedown', function(e) { e.preventDefault(); selectOpt(o); });
        });
    });
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

// Notification dropdown
var _notifLoaded = false;
function loadNotifs() {
    if (_notifLoaded) return;
    _notifLoaded = true;
    fetch('/api/notifications').then(function(r) { return r.json(); }).then(function(items) {
        var list = document.getElementById('notifList');
        if (!list) return;
        if (!items || !items.length) {
            list.innerHTML = '<li class="text-center text-muted small py-3">暂无新通知</li>';
            return;
        }
        var h = '<li><div class="px-3 py-1 border-bottom"><span class="small fw-bold">通知</span></div></li>';
        items.forEach(function(n) {
            h += '<li class="d-flex align-items-start">'
                + '<a class="dropdown-item small py-2 flex-grow-1" href="' + (n.link || '#') + '" onclick="markRead(' + n.id + ')">'
                + '<i class="bi bi-' + n.icon + ' me-1 text-muted"></i>'
                + '<span class="text-muted" style="font-size:.75em;">[' + n.type_label + ']</span> '
                + n.title
                + '<div class="text-muted" style="font-size:.7em;">' + n.time + '</div>'
                + '</a>'
                + '<button class="btn btn-sm border-0 text-muted px-2 py-2" onclick="markRead(' + n.id + ');this.closest(\'li\').remove();updateBadge(-1);" title="已读"><i class="bi bi-x"></i></button>'
                + '</li>';
        });
        list.innerHTML = h;
    });
}
function markRead(nid) {
    apiPost('/api/notifications/read', {id: nid});
}
function updateBadge(delta) {
    var badge = document.getElementById('notifBadge');
    if (!badge) return;
    var cur = parseInt(badge.textContent) || 0;
    var next = Math.max(0, cur + delta);
    badge.textContent = next;
    badge.style.display = next > 0 ? '' : 'none';
}
