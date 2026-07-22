/* Hermes KB 共享导航注入 + chunk 高亮逻辑
 * 每个页面 <body data-page="xxx"> 控制 active 状态；
 * 解析 ?chunk=N 参数，DOMContentLoaded 后滚动到 #chunk-N 并高亮。
 */
(function () {
  var NAV_ITEMS = [
    { href: 'index.html', label: '首页', page: 'home' },
    { href: 'ask.html', label: '问答', page: 'ask' },
    { href: 'docs.html', label: '文档', page: 'docs' },
    { href: 'tags.html', label: '标签', page: 'tags' },
    { href: 'history.html', label: '历史', page: 'history' },
    { href: 'dashboard.html', label: '仪表盘', page: 'dashboard' },
    { href: 'audit.html', label: '审计', page: 'audit' }
  ];

  function buildNav() {
    var nav = document.createElement('nav');
    nav.className = 'nav';
    var c = document.createElement('div');
    c.className = 'container';
    var brand = document.createElement('a');
    brand.href = 'index.html';
    brand.className = 'nav-brand';
    brand.textContent = 'Hermes KB';
    c.appendChild(brand);
    var ul = document.createElement('ul');
    ul.className = 'nav-links';
    var currentPage = document.body.dataset.page || '';
    NAV_ITEMS.forEach(function (item) {
      var li = document.createElement('li');
      var a = document.createElement('a');
      a.href = item.href;
      a.textContent = item.label;
      if (item.page === currentPage) a.className = 'active';
      li.appendChild(a);
      ul.appendChild(li);
    });
    c.appendChild(ul);
    var actions = document.createElement('div');
    actions.className = 'nav-actions';
    actions.innerHTML =
      '<a class="btn-ghost" href="_modal-import.html">导入</a>' +
      '<a class="btn-ghost" href="export.html">导出</a>' +
      '<a class="btn-primary" href="_modal-login.html">登录</a>';
    c.appendChild(actions);
    nav.appendChild(c);
    document.body.insertBefore(nav, document.body.firstChild);
  }

  function highlightChunk() {
    var params = new URLSearchParams(window.location.search);
    var n = params.get('chunk');
    if (!n) return;
    var target = document.getElementById('chunk-' + n);
    if (!target) return;
    // 滚动定位（< 500ms，依赖 CSS scroll-behavior: smooth）
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    // 2000ms 淡金高亮动画
    target.classList.add('chunk-highlight');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { buildNav(); highlightChunk(); });
  } else {
    buildNav();
    highlightChunk();
  }
})();
