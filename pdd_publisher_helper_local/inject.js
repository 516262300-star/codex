// inject.js — 注入到页面上下文中，监听影刀RPA通过 window.postMessage 发送的数据
// 并通过 CustomEvent 转发给 content script
(function () {
  'use strict';

  window.addEventListener('message', function (event) {
    // 只处理来自当前窗口的消息
    if (event.source !== window) return;
    if (!event.data || !event.data.type) return;

    if (event.data.type === 'PDD_FILL_ATTRIBUTES') {
      document.dispatchEvent(new CustomEvent('pdd-fill-attributes', {
        detail: event.data.data
      }));
    } else if (event.data.type === 'PDD_FILL_TITLE') {
      document.dispatchEvent(new CustomEvent('pdd-fill-title', {
        detail: event.data.data
      }));
    } else if (event.data.type === 'PDD_UPLOAD_IMAGES') {
      document.dispatchEvent(new CustomEvent('pdd-upload-images', {
        detail: event.data.data
      }));
    } else if (event.data.type === 'PDD_UPLOAD_DETAIL_IMAGES') {
      document.dispatchEvent(new CustomEvent('pdd-upload-detail-images', {
        detail: event.data.data
      }));
    } else if (event.data.type === 'PDD_UPLOAD_SKU_IMAGES') {
      document.dispatchEvent(new CustomEvent('pdd-upload-sku-images', {
        detail: event.data.data
      }));
    } else if (event.data.type === 'PDD_FILL_SKU') {
      document.dispatchEvent(new CustomEvent('pdd-fill-sku', {
        detail: event.data.data
      }));
    }
  });

  console.log('[PDD填充插件] inject.js 已加载，等待接收数据...');
})();
