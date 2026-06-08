// Local safe background service worker.
// This file intentionally cannot open tabs, run promotion tasks, or poll queues.

var LOG = '[PDD-BG-SAFE]';
var QUEUE_STORAGE_KEY = 'pdd_task_queue';
var QUEUE_LOG_KEY = 'pdd_queue_log';

function clearLegacyQueueState() {
  var empty = {};
  empty[QUEUE_STORAGE_KEY] = [];
  empty[QUEUE_LOG_KEY] = [];
  empty.pdd_processed_ids = [];
  chrome.storage.local.set(empty, function () {
    console.log(LOG, 'cleared legacy queue state');
  });
}

function blobToDataUrl(blob) {
  return new Promise(function (resolve, reject) {
    var reader = new FileReader();
    reader.onloadend = function () { resolve(reader.result); };
    reader.onerror = function () { reject(new Error('failed to read image blob')); };
    reader.readAsDataURL(blob);
  });
}

chrome.runtime.onInstalled.addListener(function () {
  clearLegacyQueueState();
});

chrome.runtime.onStartup.addListener(function () {
  clearLegacyQueueState();
});

clearLegacyQueueState();

chrome.runtime.onMessage.addListener(function (message, sender, sendResponse) {
  message = message || {};

  if (message.type === 'FETCH_IMAGE') {
    fetch(message.url, { credentials: 'omit' })
      .then(function (response) {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.blob();
      })
      .then(blobToDataUrl)
      .then(function (dataUrl) {
        sendResponse({ success: true, dataUrl: dataUrl });
      })
      .catch(function (error) {
        sendResponse({ success: false, error: error.message });
      });
    return true;
  }

  if (message.type === 'GET_STATUS') {
    sendResponse({
      state: 'LOCAL_SAFE_IDLE',
      pollingEnabled: false,
      productId: null,
      productName: null
    });
    return false;
  }

  if (message.type === 'GET_PRODUCT_DATA') {
    sendResponse({
      state: 'LOCAL_SAFE_IDLE',
      productData: null,
      productId: null
    });
    return false;
  }

  if (message.type === 'CLEAR_LEGACY_TASKS' || message.type === 'QUEUE_CLEAR') {
    clearLegacyQueueState();
    sendResponse({ ok: true });
    return false;
  }

  if (
    message.type === 'TRIGGER_MAINTENANCE' ||
    message.type === 'QUEUE_PROCESS' ||
    message.type === 'MANUAL_TRIGGER' ||
    message.type === 'TOGGLE_POLLING' ||
    message.type === 'SAVE_CONFIG'
  ) {
    clearLegacyQueueState();
    sendResponse({ ok: false, error: 'local safe mode: disabled' });
    return false;
  }

  sendResponse({ ok: false, error: 'unsupported in local safe mode' });
  return false;
});
