(function () {
  'use strict';

  function $(id) {
    return document.getElementById(id);
  }

  var logs = [];

  function addLog(message) {
    var time = new Date().toLocaleTimeString();
    logs.push('[' + time + '] ' + message);
    if (logs.length > 20) logs.shift();
    $('logArea').textContent = logs.join('\n');
    $('logArea').scrollTop = $('logArea').scrollHeight;
  }

  function setStatus(text, ok) {
    $('statusText').textContent = text;
    $('statusDot').style.background = ok ? '#12b76a' : '#f79009';
  }

  function refreshStatus() {
    chrome.runtime.sendMessage({ type: 'GET_STATUS' }, function (response) {
      if (chrome.runtime.lastError) {
        setStatus('扩展后台未响应，请重新加载扩展', false);
        addLog('状态读取失败: ' + chrome.runtime.lastError.message);
        return;
      }
      var state = response && response.state ? response.state : 'UNKNOWN';
      setStatus('当前状态: ' + state, state === 'LOCAL_SAFE_IDLE');
      addLog('状态已刷新: ' + state);
    });
  }

  function clearLegacyTasks() {
    chrome.runtime.sendMessage({ type: 'CLEAR_LEGACY_TASKS' }, function (response) {
      if (chrome.runtime.lastError) {
        addLog('清理失败: ' + chrome.runtime.lastError.message);
        return;
      }
      if (response && response.ok) {
        addLog('旧数据已清理');
      } else {
        addLog('清理命令已发送');
      }
      refreshStatus();
    });
  }

  $('btnRefresh').addEventListener('click', refreshStatus);
  $('btnClearLegacy').addEventListener('click', clearLegacyTasks);

  addLog('本地安全版弹窗已加载');
  refreshStatus();
})();
