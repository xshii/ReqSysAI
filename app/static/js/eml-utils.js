/**
 * EML Export Utilities
 * Shared MIME/base64 EML generation for all export pages.
 *
 * Public API:
 *   emlEncodeHeader(s)          – RFC 2047 UTF-8 B-encoding
 *   emlBadgeMap / emlTextMap     – Bootstrap→inline-style maps
 *   emlInlineStyles(html)       – Convert badge/text classes to inline styles
 *   emlSection(title, body, titleColor, secIdx) – Wrap a section in <tr>
 *   emlTable(tableEl)           – Clone a <table> DOM element to inline-styled HTML
 *   emlRecipientBlock(to, cc)   – Build To/Cc display block
 *   emlWrapHtml(rows, opts)     – Wrap rows in full HTML document
 *   emlBuildFile(subject, html) – Build complete EML string
 *   emlDownload(filename, eml)  – Trigger download and cleanup
 */

/* ── RFC 2047 header encoding ── */
function emlEncodeHeader(s) {
    return '=?UTF-8?B?' + btoa(unescape(encodeURIComponent(s))) + '?=';
}

/* ── Bootstrap class → inline style maps ── */
var emlBadgeMap = {
    'bg-success':   'background:#198754;color:#fff;',
    'bg-primary':   'background:#0d6efd;color:#fff;',
    'bg-warning':   'background:#ffc107;color:#333;',
    'bg-secondary': 'background:#6c757d;color:#fff;',
    'bg-danger':    'background:#dc3545;color:#fff;',
    'bg-info':      'background:#0dcaf0;color:#333;',
    'bg-dark':      'background:#212529;color:#fff;'
};
var emlTextMap = {
    'text-success':   'color:#198754;',
    'text-primary':   'color:#0d6efd;',
    'text-warning':   'color:#ffc107;',
    'text-danger':    'color:#dc3545;',
    'text-secondary': 'color:#6c757d;',
    'text-muted':     'color:#6c757d;',
    'text-info':      'color:#0dcaf0;',
    'fw-bold':        'font-weight:700;'
};

/* ── Convert Bootstrap badge/text classes to inline styles ── */
function emlInlineStyles(html) {
    html = html.replace(/<span\s+class="badge\s+([^"]+)"/g, function(m, cls) {
        var s = 'display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;';
        cls.split(/\s+/).forEach(function(c) { if (emlBadgeMap[c]) s += emlBadgeMap[c]; });
        return '<span style="' + s + '"';
    });
    html = html.replace(/<span\s+class="([^"]*(?:text-|fw-)[^"]*)"/g, function(m, cls) {
        var s = '';
        cls.split(/\s+/).forEach(function(c) { if (emlTextMap[c]) s += emlTextMap[c]; });
        return s ? '<span style="' + s + '"' : m;
    });
    return html;
}

/* ── Section row: coloured title bar + body ── */
function emlSection(title, body, titleColor, secIdx) {
    var c = titleColor || '#4a5568';
    var anchor = secIdx !== undefined ? '<a name="sec-' + secIdx + '"></a>' : '';
    return '<tr><td colspan="99" style="background:' + c + ';color:#fff;padding:7px 16px;font-size:13px;font-weight:600;">' + anchor + title + '</td></tr>'
        + '<tr><td colspan="99" style="padding:4px 12px 4px;font-size:13px;color:#4a5568;">' + body + '</td></tr>';
}

/* ── Convert a DOM <table> to inline-styled HTML for Outlook ── */
function emlTable(tableEl) {
    if (!tableEl) return '';
    var h = '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:13px;">';
    tableEl.querySelectorAll('tr').forEach(function(tr, ri) {
        h += '<tr' + (tr.classList.contains('row-risk') ? ' style="background:#fef2f2;"' : (ri > 0 && ri % 2 === 0 ? ' style="background:#fafbfc;"' : '')) + '>';
        tr.querySelectorAll('th,td').forEach(function(cell) {
            var tag = cell.tagName.toLowerCase();
            var bg = tag === 'th' ? 'background:#f7fafc;font-weight:600;color:#4a5568;' : '';
            var attrs = '';
            if (cell.getAttribute('colspan')) attrs += ' colspan="' + cell.getAttribute('colspan') + '"';
            if (cell.getAttribute('rowspan')) attrs += ' rowspan="' + cell.getAttribute('rowspan') + '"';
            var cellBg = cell.style.background || cell.style.backgroundColor || '';
            if (cellBg) bg += 'background:' + cellBg + ';';
            var align = cell.style.textAlign; if (align) bg += 'text-align:' + align + ';';
            h += '<' + tag + attrs + ' style="border:1px solid #718096;padding:4px 8px;' + bg + '">' + emlInlineStyles(cell.innerHTML) + '</' + tag + '>';
        });
        h += '</tr>';
    });
    return h + '</table>';
}

/* ── To/Cc recipient block for email body ── */
function emlRecipientBlock(to, cc) {
    if (!to && !cc) return '';
    var html = '<table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:2px;font-size:12px;color:#64748b;">';
    if (to) html += '<tr><td style="padding:2px 16px;"><b>To:</b> ' + to + '</td></tr>';
    if (cc) html += '<tr><td style="padding:2px 16px;"><b>Cc:</b> ' + cc + '</td></tr>';
    html += '</table>';
    return html;
}

/**
 * Wrap rows in a full HTML document suitable for EML embedding.
 * @param {string} rows - Inner table rows HTML
 * @param {object} opts
 * @param {string} opts.to - Resolved To string
 * @param {string} opts.cc - Resolved Cc string
 * @param {string} opts.fontFamily - Override font-family (default: Microsoft YaHei,Segoe UI,sans-serif)
 * @param {string} opts.bodyBg - Body background colour (default: #ffffff)
 * @param {string} opts.tableBorder - Optional border on main table (e.g. '1px solid #e2e8f0')
 */
function emlWrapHtml(rows, opts) {
    opts = opts || {};
    var font = opts.fontFamily || 'Microsoft YaHei,Segoe UI,sans-serif';
    var bodyBg = opts.bodyBg || '#ffffff';
    var border = opts.tableBorder ? 'border:' + opts.tableBorder + ';' : '';
    var recipientBlock = emlRecipientBlock(opts.to || '', opts.cc || '');
    return '<html><head><meta charset="UTF-8"></head><body style="font-family:' + font + ';margin:0;padding:0;background:' + bodyBg + ';">'
        + '<table width="100%" cellpadding="0" cellspacing="0"><tr><td style="padding:20px;">'
        + recipientBlock
        + '<table width="100%" cellpadding="0" cellspacing="0" style="max-width:800px;margin:0 auto;background:#fff;' + border + '">'
        + rows + '</table></td></tr></table></body></html>';
}

/**
 * Build a complete EML file string from subject + HTML body.
 * @param {string} subject - Email subject (plain text, will be B-encoded)
 * @param {string} htmlContent - Full HTML document string
 * @returns {string} EML file content
 */
function emlBuildFile(subject, htmlContent) {
    var boundary = 'boundary_' + Date.now();
    return [
        'Subject: ' + emlEncodeHeader(subject),
        'MIME-Version: 1.0',
        'Content-Type: multipart/alternative; boundary="' + boundary + '"',
        'X-Unsent: 1',
        '', '--' + boundary,
        'Content-Type: text/html; charset=UTF-8',
        'Content-Transfer-Encoding: base64',
        '', btoa(unescape(encodeURIComponent(htmlContent))).match(/.{1,76}/g).join('\n'),
        '', '--' + boundary + '--'
    ].join('\r\n');
}

/**
 * Trigger download of an EML file and clean up the object URL.
 * @param {string} filename - Download filename (without .eml extension — it will NOT be added automatically)
 * @param {string} emlString - Full EML content
 */
function emlDownload(filename, emlString) {
    var blob = new Blob([emlString], {type: 'message/rfc822'});
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    setTimeout(function() { URL.revokeObjectURL(url); }, 1000);
}
