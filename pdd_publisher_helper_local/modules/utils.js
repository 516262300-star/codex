// utils.js - 公共工具函数模块
/**
 * @typedef {import('../types').Logger} Logger
 * @typedef {import('../types').ValidationResult} ValidationResult
 * @typedef {import('../types').ImageValidationResult} ImageValidationResult
 * @typedef {import('../types').FinderFunction} FinderFunction
 * @typedef {import('../types').CheckerFunction} CheckerFunction
 * @typedef {import('../types').DelayFunction} DelayFunction
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.Utils = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var ErrorType = {
    NOT_FOUND: 'NOT_FOUND',
    VALIDATION_ERROR: 'VALIDATION_ERROR',
    NETWORK_ERROR: 'NETWORK_ERROR',
    TIMEOUT: 'TIMEOUT',
    UNKNOWN: 'UNKNOWN'
  };

  var DEBUG_MODE = false;

  var activeObservers = [];
  var activeTimers = [];

  /**
   * Logger类 - 日志记录工具
   * @class
   * @param {string} [prefix='[PDD填充插件]'] - 日志前缀
   */
  function Logger(prefix) {
    this.prefix = prefix || '[PDD填充插件]';
  }

  Logger.prototype.debug = function () {
    if (!DEBUG_MODE) return;
    var args = Array.prototype.slice.call(arguments);
    args.unshift(this.prefix + '[DEBUG]');
    console.debug.apply(console, args);
  };

  Logger.prototype.info = function () {
    var args = Array.prototype.slice.call(arguments);
    args.unshift(this.prefix + '[INFO]');
    console.info.apply(console, args);
  };

  Logger.prototype.warn = function () {
    var args = Array.prototype.slice.call(arguments);
    args.unshift(this.prefix + '[WARN]');
    console.warn.apply(console, args);
  };

  Logger.prototype.error = function () {
    var args = Array.prototype.slice.call(arguments);
    args.unshift(this.prefix + '[ERROR]');
    console.error.apply(console, args);
  };

  /**
   * 设置调试模式
   * @param {boolean} enabled - 是否启用调试模式
   */
  Logger.setDebugMode = function (enabled) {
    DEBUG_MODE = !!enabled;
  };

  /**
   * 获取调试模式状态
   * @returns {boolean} 当前调试模式状态
   */
  Logger.getDebugMode = function () {
    return DEBUG_MODE;
  };

  /**
   * 延迟函数
   * @param {number} ms - 延迟毫秒数
   * @returns {Promise<void>} Promise对象
   */
  function delay(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  /**
   * 模拟鼠标点击事件
   * @param {Element} el - 目标元素
   */
  function simulateClick(el) {
    el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return Promise.resolve();
  }

  /**
   * 等待元素出现
   * @param {FinderFunction} finder - 元素查找函数
   * @param {number} [maxWait=3000] - 最大等待时间（毫秒）
   * @param {number} [interval=100] - 检查间隔（毫秒）
   * @returns {Promise<Element|null>} 找到的元素或null
   */
  function waitForElement(finder, maxWait, interval) {
    maxWait = maxWait || 3000;
    interval = interval || 100;
    return new Promise(function (resolve) {
      var el = finder();
      if (el) return resolve(el);

      var useObserver = typeof MutationObserver !== 'undefined' && document.body;
      var observer = null;
      var start = Date.now();

      if (useObserver) {
        try {
          observer = new MutationObserver(function () {
            var elapsed = Date.now() - start;
            if (elapsed > maxWait) {
              if (observer) {
                observer.disconnect();
                var idx = activeObservers.indexOf(observer);
                if (idx > -1) activeObservers.splice(idx, 1);
              }
              return resolve(null);
            }
            var found = finder();
            if (found) {
              if (observer) {
                observer.disconnect();
                var idx = activeObservers.indexOf(observer);
                if (idx > -1) activeObservers.splice(idx, 1);
              }
              return resolve(found);
            }
          });
          observer.observe(document.body, { childList: true, subtree: true });
          activeObservers.push(observer);
        } catch (e) {
          useObserver = false;
        }
      }

      if (!useObserver) {
        var check = function () {
          var el = finder();
          if (el) return resolve(el);
          if (Date.now() - start > maxWait) return resolve(null);
          setTimeout(check, interval);
        };
        check();
      }
    });
  }

  /**
   * 等待条件满足
   * @param {CheckerFunction} checker - 条件检查函数
   * @param {number} [maxWait=1000] - 最大等待时间（毫秒）
   * @param {number} [interval=80] - 检查间隔（毫秒）
   * @returns {Promise<boolean>} 条件是否满足
   */
  function waitForCondition(checker, maxWait, interval) {
    maxWait = maxWait || 1000;
    interval = interval || 80;
    var start = Date.now();
    return new Promise(function (resolve) {
      if (checker()) return resolve(true);

      var useObserver = typeof MutationObserver !== 'undefined' && document.body;
      var observer = null;

      if (useObserver) {
        try {
          observer = new MutationObserver(function () {
            var elapsed = Date.now() - start;
            if (elapsed > maxWait) {
              if (observer) {
                observer.disconnect();
                var idx = activeObservers.indexOf(observer);
                if (idx > -1) activeObservers.splice(idx, 1);
              }
              return resolve(false);
            }
            try {
              if (checker()) {
                if (observer) {
                  observer.disconnect();
                  var idx = activeObservers.indexOf(observer);
                  if (idx > -1) activeObservers.splice(idx, 1);
                }
                return resolve(true);
              }
            } catch (e) {}
          });
          observer.observe(document.body, { childList: true, subtree: true });
          activeObservers.push(observer);
        } catch (e) {
          useObserver = false;
        }
      }

      if (!useObserver) {
        var tick = function () {
          try {
            if (checker()) return resolve(true);
          } catch (e) {}
          if (Date.now() - start <= maxWait) {
            delay(interval).then(tick);
          } else {
            resolve(false);
          }
        };
        tick();
      }
    });
  }

  /**
   * 检查元素是否可见
   * @param {Element|null} el - 要检查的元素
   * @returns {boolean} 元素是否可见
   */
  function isElementVisible(el) {
    if (!el || !document.contains(el)) return false;
    var rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) return false;
    var style = window.getComputedStyle(el);
    return style.display !== 'none' && style.visibility !== 'hidden';
  }

  /**
   * 稳定的JSON序列化（按键排序）
   * @param {any} value - 要序列化的值
   * @returns {string} 序列化后的字符串
   */
  function stableStringify(value) {
    if (value === null || value === undefined) return String(value);
    if (typeof value !== 'object') return JSON.stringify(value);
    if (Array.isArray(value)) return '[' + value.map(stableStringify).join(',') + ']';
    var keys = Object.keys(value).sort();
    var pairs = keys.map(function (k) {
      return JSON.stringify(k) + ':' + stableStringify(value[k]);
    });
    return '{' + pairs.join(',') + '}';
  }

  /**
   * 规范化文本（移除多余空白）
   * @param {string} text - 要规范化的文本
   * @returns {string} 规范化后的文本
   */
  function normalizeText(text) {
    return String(text || '').replace(/\s+/g, '').trim();
  }

  /**
   * 验证输入数据
   * @param {Object.<string, any>} data - 要验证的数据对象
   * @param {Object.<string, Object>} [schema] - 验证规则
   * @returns {ValidationResult} 验证结果
   */
  function validateInput(data, schema) {
    var errors = [];
    if (!schema) return { valid: true, errors: [] };

    for (var field in schema) {
      if (!schema.hasOwnProperty(field)) continue;
      var rules = schema[field];
      var value = data[field];

      if (rules.required && (value === undefined || value === null || value === '')) {
        errors.push(field + ' 是必填字段');
        continue;
      }

      if (value !== undefined && value !== null && value !== '') {
        if (rules.type === 'string' && typeof value !== 'string') {
          errors.push(field + ' 必须是字符串');
        }
        if (rules.type === 'array' && !Array.isArray(value)) {
          errors.push(field + ' 必须是数组');
        }
        if (rules.type === 'number' && typeof value !== 'number') {
          errors.push(field + ' 必须是数字');
        }
        if (rules.minLength && value.length < rules.minLength) {
          errors.push(field + ' 长度不能小于 ' + rules.minLength);
        }
        if (rules.maxLength && value.length > rules.maxLength) {
          errors.push(field + ' 长度不能大于 ' + rules.maxLength);
        }
        if (rules.pattern && !rules.pattern.test(value)) {
          errors.push(field + ' 格式不正确');
        }
      }
    }

    return { valid: errors.length === 0, errors: errors };
  }

  /**
   * 验证图片URL格式
   * @param {string} url - 图片URL
   * @returns {ImageValidationResult} 验证结果
   */
  function validateImageUrl(url) {
    if (!url || typeof url !== 'string') {
      return { valid: false, error: '图片URL无效' };
    }
    url = url.trim();
    if (url.length === 0) {
      return { valid: false, error: '图片URL为空' };
    }
    try {
      var parsed = new URL(url);
      if (!['http:', 'https:'].includes(parsed.protocol)) {
        return { valid: false, error: '图片URL协议不支持' };
      }
      return { valid: true, error: null };
    } catch (e) {
      if (/^data:image/i.test(url)) {
        return { valid: true, error: null };
      }
      return { valid: false, error: '图片URL格式不正确' };
    }
  }

  /**
   * 创建 MutationObserver 并自动跟踪
   * @param {Element|string} target - 观察目标元素或选择器
   * @param {MutationObserverInit} [options] - 观察配置
   * @param {Function} callback - 回调函数
   * @param {number} [timeout] - 超时时间（毫秒），0表示不超时
   * @returns {Promise<{observer: MutationObserver, element: Element|null, cleanup: Function}>}
   */
  function createMutationObserver(target, options, callback, timeout) {
    options = options || { childList: true, subtree: true };
    timeout = timeout || 0;

    return new Promise(function (resolve) {
      var resolved = false;
      var observer = null;
      var element = null;
      var timeoutId = null;

      if (typeof target === 'string') {
        element = document.querySelector(target);
      } else {
        element = target;
      }

      if (!element) {
        if (!resolved) {
          resolved = true;
          resolve({ observer: null, element: null, cleanup: function () {} });
        }
        return;
      }

      var defaultCallback = callback;
      var wrappedCallback = function (mutations, obs) {
        if (resolved) return;
        try {
          var shouldResolve = defaultCallback(mutations, obs);
          if (shouldResolve && timeout > 0) {
            resolved = true;
            cleanup();
            resolve({ observer: obs, element: element, cleanup: cleanup });
          } else if (shouldResolve && timeout === 0) {
          }
        } catch (e) {
          console.error('[PDD填充插件] MutationObserver 回调错误:', e);
        }
      };

      try {
        observer = new MutationObserver(wrappedCallback);
        observer.observe(element, options);
        activeObservers.push(observer);
      } catch (e) {
        console.error('[PDD填充插件] 创建 MutationObserver 失败:', e);
        if (!resolved) {
          resolved = true;
          resolve({ observer: null, element: element, cleanup: function () {} });
        }
        return;
      }

      function cleanup() {
        if (timeoutId) {
          clearTimeout(timeoutId);
          timeoutId = null;
        }
        if (observer) {
          try {
            observer.disconnect();
          } catch (e) {}
          var idx = activeObservers.indexOf(observer);
          if (idx > -1) {
            activeObservers.splice(idx, 1);
          }
          observer = null;
        }
      }

      if (timeout > 0) {
        timeoutId = setTimeout(function () {
          if (!resolved) {
            resolved = true;
            cleanup();
            resolve({ observer: null, element: element, cleanup: cleanup });
          }
        }, timeout);
      }

      resolve({
        observer: observer,
        element: element,
        cleanup: cleanup
      });
    });
  }

  /**
   * 使用 MutationObserver 等待元素出现
   * @param {Element|string} container - 容器元素或选择器
   * @param {string} selector - 目标元素选择器
   * @param {Object} [options] - 配置选项
   * @param {number} [options.timeout=5000] - 超时时间（毫秒）
   * @param {boolean} [options.multiple=false] - 是否返回多个元素
   * @param {MutationObserverInit} [options.observeOptions] - 观察配置
   * @returns {Promise<Element|Element[]|null>}
   */
  function waitForElementWithObserver(container, selector, options) {
    options = options || {};
    var timeout = options.timeout !== undefined ? options.timeout : 5000;
    var multiple = options.multiple || false;
    var observeOptions = options.observeOptions || { childList: true, subtree: true };

    return new Promise(function (resolve) {
      var containerEl = typeof container === 'string' ? document.querySelector(container) : container;

      if (!containerEl) {
        resolve(null);
        return;
      }

      var found = multiple ? [] : null;
      var checkExisting = function () {
        var els = containerEl.querySelectorAll(selector);
        if (els.length > 0) {
          if (multiple) {
            found = Array.prototype.slice.call(els);
          } else {
            found = els[0];
          }
          return true;
        }
        return false;
      };

      if (checkExisting()) {
        resolve(found);
        return;
      }

      var observer = null;
      var timeoutId = null;
      var resolved = false;

      function cleanup() {
        if (timeoutId) {
          clearTimeout(timeoutId);
          timeoutId = null;
        }
        if (observer) {
          try {
            observer.disconnect();
          } catch (e) {}
          var idx = activeObservers.indexOf(observer);
          if (idx > -1) {
            activeObservers.splice(idx, 1);
          }
          observer = null;
        }
      }

      function doResolve(result) {
        if (resolved) return;
        resolved = true;
        cleanup();
        resolve(result);
      }

      observer = new MutationObserver(function (mutations) {
        if (resolved) return;
        if (checkExisting()) {
          doResolve(found);
        }
      });

      try {
        observer.observe(containerEl, observeOptions);
        activeObservers.push(observer);
      } catch (e) {
        console.error('[PDD填充插件] 观察失败:', e);
        resolve(null);
        return;
      }

      if (timeout > 0) {
        timeoutId = setTimeout(function () {
          doResolve(null);
        }, timeout);
      }
    });
  }

  /**
   * 清理所有观察者和定时器
   * @returns {Object} 清理结果 { observersCleared: number, timersCleared: number }
   */
  function cleanupObservers() {
    var observersCleared = 0;
    var timersCleared = 0;

    for (var i = 0; i < activeObservers.length; i++) {
      try {
        activeObservers[i].disconnect();
        observersCleared++;
      } catch (e) {}
    }
    activeObservers = [];

    for (var j = 0; j < activeTimers.length; j++) {
      try {
        clearTimeout(activeTimers[j]);
        timersCleared++;
      } catch (e) {}
    }
    activeTimers = [];

    return { observersCleared: observersCleared, timersCleared: timersCleared };
  }

  /**
   * 注册一个定时器以便后续清理
   * @param {number} timerId - setTimeout 返回的定时器ID
   */
  function registerTimer(timerId) {
    if (timerId) {
      activeTimers.push(timerId);
    }
  }

  /**
   * 取消注册并清理一个定时器
   * @param {number} timerId - setTimeout 返回的定时器ID
   */
  function unregisterTimer(timerId) {
    if (!timerId) return;
    var idx = activeTimers.indexOf(timerId);
    if (idx > -1) {
      activeTimers.splice(idx, 1);
    }
    try {
      clearTimeout(timerId);
    } catch (e) {}
  }

  /**
   * 获取当前活跃的观察者数量
   * @returns {number}
   */
  function getActiveObserverCount() {
    return activeObservers.length;
  }

  /**
   * 获取当前活跃的定时器数量
   * @returns {number}
   */
  function getActiveTimerCount() {
    return activeTimers.length;
  }

  return {
    ErrorType: ErrorType,
    Logger: Logger,
    DEBUG_MODE: DEBUG_MODE,
    delay: delay,
    simulateClick: simulateClick,
    waitForElement: waitForElement,
    waitForCondition: waitForCondition,
    isElementVisible: isElementVisible,
    stableStringify: stableStringify,
    normalizeText: normalizeText,
    validateInput: validateInput,
    validateImageUrl: validateImageUrl,
    createMutationObserver: createMutationObserver,
    waitForElementWithObserver: waitForElementWithObserver,
    cleanupObservers: cleanupObservers,
    registerTimer: registerTimer,
    unregisterTimer: unregisterTimer,
    getActiveObserverCount: getActiveObserverCount,
    getActiveTimerCount: getActiveTimerCount
  };
}));