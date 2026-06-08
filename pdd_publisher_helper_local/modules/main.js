// main.js - 主入口模块
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.MainModule = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var MAX_TOAST_COUNT = 3;
  var TOAST_DURATION = 4000;
  var TOAST_LONG_DURATION = 6000;
  var TOAST_SHORT_DURATION = 2000;

  function ToastManager() {
    this.container = null;
    this.toasts = [];
    this.typeStacks = {};
    this.init();
  }

  ToastManager.prototype.init = function () {
    if (this.container) return;
    this.container = document.createElement('div');
    Object.assign(this.container.style, {
      position: 'fixed',
      top: '20px',
      right: '20px',
      zIndex: '99999',
      display: 'flex',
      flexDirection: 'column',
      gap: '8px',
      pointerEvents: 'none'
    });
    document.body.appendChild(this.container);
  };

  ToastManager.prototype.show = function (message, type, duration) {
    type = type || 'info';
    duration = duration || TOAST_DURATION;

    this.init();

    var typeStack = this.typeStacks[type] || { messages: [], elements: [], timeout: null };
    var sameTypeCount = this.toasts.filter(function (t) { return t.type === type; }).length;

    if (sameTypeCount >= MAX_TOAST_COUNT) {
      var oldestOfType = null;
      var oldestIndex = -1;
      for (var i = 0; i < this.toasts.length; i++) {
        if (this.toasts[i].type === type) {
          oldestOfType = this.toasts[i];
          oldestIndex = i;
          break;
        }
      }
      if (oldestOfType) {
        this.removeToast(oldestOfType);
      }
    }

    var el = document.createElement('div');
    var colors = {
      info: { bg: '#e6f7ff', border: '#91d5ff', text: '#096dd9' },
      success: { bg: '#f6ffed', border: '#b7eb8f', text: '#389e0d' },
      error: { bg: '#fff2f0', border: '#ffccc7', text: '#cf1322' },
      warning: { bg: '#fffbe6', border: '#ffe58f', text: '#d48806' }
    };
    var c = colors[type] || colors.info;

    Object.assign(el.style, {
      background: c.bg,
      border: '1px solid ' + c.border,
      color: c.text,
      padding: '10px 16px',
      borderRadius: '6px',
      fontSize: '14px',
      lineHeight: '1.5',
      boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
      maxWidth: '400px',
      wordBreak: 'break-all',
      pointerEvents: 'auto',
      transition: 'opacity 0.3s',
      opacity: '0'
    });

    el.textContent = message;
    this.container.appendChild(el);

    var toastObj = { el: el, type: type, message: message };
    this.toasts.push(toastObj);

    requestAnimationFrame(function () {
      el.style.opacity = '1';
    });

    var self = this;
    var timeoutId = setTimeout(function () {
      el.style.opacity = '0';
      setTimeout(function () {
        self.removeToast(toastObj);
      }, 300);
    }, duration);

    el.addEventListener('click', function () {
      el.style.opacity = '0';
      setTimeout(function () {
        self.removeToast(toastObj);
      }, 300);
    });

    toastObj.timeoutId = timeoutId;
    return toastObj;
  };

  ToastManager.prototype.updateProgress = function (message, type, toastObj) {
    if (!toastObj || !document.contains(toastObj.el)) {
      return this.show(message, type, TOAST_SHORT_DURATION);
    }
    toastObj.el.textContent = message;
    return toastObj;
  };

  ToastManager.prototype.removeToast = function (toastObj) {
    if (!toastObj) return;
    if (toastObj.timeoutId) {
      clearTimeout(toastObj.timeoutId);
    }
    if (document.contains(toastObj.el)) {
      toastObj.el.remove();
    }
    var idx = this.toasts.indexOf(toastObj);
    if (idx !== -1) {
      this.toasts.splice(idx, 1);
    }
  };

  ToastManager.prototype.clear = function () {
    for (var i = this.toasts.length - 1; i >= 0; i--) {
      this.removeToast(this.toasts[i]);
    }
    this.toasts = [];
    this.typeStacks = {};
  };

  var Toast = new ToastManager();

  function extractLabelText(propertyListEl) {
    var label = propertyListEl.querySelector('[class*="Form_itemLabelContent"]');
    if (!label) return '';

    var innerSpans = label.querySelectorAll('span[style*="font-size"]');
    if (innerSpans.length > 0) {
      for (var i = 0; i < innerSpans.length; i++) {
        var txt = innerSpans[i].textContent.trim();
        if (txt && txt !== '重要') return txt;
      }
    }

    return label.textContent.trim();
  }

  function buildPropertyMap() {
    var map = new Map();
    var propertyLists = document.querySelectorAll('[id^="property-list-"]');
    for (var pi = 0; pi < propertyLists.length; pi++) {
      var pl = propertyLists[pi];
      var name = extractLabelText(pl);
      if (name) {
        map.set(name, pl);
      }
    }

    var formItems = document.querySelectorAll('[data-testid="beast-core-form-item"][id^="basic."]');
    for (var fi = 0; fi < formItems.length; fi++) {
      var item = formItems[fi];
      var name = extractLabelText(item);
      if (name && !map.has(name)) {
        map.set(name, item);
      }
    }
    return map;
  }

  function findPropertyEl(name, propertyMap) {
    var el = propertyMap.get(name);
    if (el) return { el: el, matchedKey: name };

    var keys = Array.from(propertyMap.keys());
    for (var i = 0; i < keys.length; i++) {
      var key = keys[i];
      if (key.includes(name) || name.includes(key)) {
        console.log('[PDD填充插件] 模糊匹配: "' + name + '" → "' + key + '"');
        return { el: propertyMap.get(key), matchedKey: key };
      }
    }
    return null;
  }

  function findTitleInput() {
    // 策略1: 直接查找 #goods_name (新结构)
    var formItem = document.querySelector('#goods_name');
    if (formItem) {
      var input = formItem.querySelector('[data-testid="beast-core-input-htmlInput"]');
      if (input) {
        console.log('[PDD填充插件] 通过 #goods_name 找到标题输入框');
        return input;
      }
    }

    // 策略2: 查找 #basic.goods_name (旧结构)
    formItem = document.querySelector('#basic\\.goods_name');
    if (formItem) {
      var input = formItem.querySelector('[data-testid="beast-core-input-htmlInput"]');
      if (input) {
        console.log('[PDD填充插件] 通过 #basic.goods_name 找到标题输入框');
        return input;
      }
    }

    // 策略3: 通过 placeholder 包含"商品标题"查找
    var allInputs = document.querySelectorAll('[data-testid="beast-core-input-htmlInput"]');
    for (var i = 0; i < allInputs.length; i++) {
      var inp = allInputs[i];
      var placeholder = inp.placeholder || '';
      if (placeholder.includes('商品标题') || placeholder.includes('商品描述')) {
        console.log('[PDD填充插件] 通过 placeholder 找到标题输入框');
        return inp;
      }
    }

    // 策略4: 通过标签文本"商品标题"查找 (原有逻辑)
    var labels = document.querySelectorAll('[class*="Form_itemLabelContent"]');
    for (var j = 0; j < labels.length; j++) {
      if (labels[j].textContent.includes('商品标题')) {
        var formItemEl = labels[j].closest('[data-testid="beast-core-form-item"]');
        if (formItemEl) {
          var input = formItemEl.querySelector('[data-testid="beast-core-input-htmlInput"]');
          if (input) {
            console.log('[PDD填充插件] 通过标签文本找到标题输入框');
            return input;
          }
        }
      }
    }
    return null;
  }

  function fillTitle(title) {
    if (!title || typeof title !== 'string') {
      Toast.show('填充失败: 商品标题数据为空或格式不正确', 'error');
      return;
    }

    console.log('[PDD填充插件] 开始填充商品标题:', title);

    var input = findTitleInput();
    if (!input) {
      Toast.show('填充失败: 商品标题输入框未找到', 'error');
      console.error('[PDD填充插件] 未找到商品标题 input 元素');
      return;
    }

    input.focus();
    input.dispatchEvent(new Event('focus', { bubbles: true }));

    var delay = function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };

    delay(100).then(function () {
      var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      if (nativeSetter) {
        nativeSetter.call(input, title);
        input.dispatchEvent(new Event('input', { bubbles: true }));
      }
      return delay(100);
    }).then(function () {
      input.dispatchEvent(new Event('blur', { bubbles: true }));
      Toast.show('PDD标题填充完成', 'success', TOAST_DURATION);
      console.log('[PDD填充插件] PDD标题填充完成');
    });
  }

  function getNativeInputValueSetter() {
    try {
      return Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    } catch (e) {
      return null;
    }
  }

  function setInputValue(input, value) {
    var nativeSetter = getNativeInputValueSetter();
    var tracker = input._valueTracker;
    if (tracker) tracker.setValue('');

    input.focus();
    input.setSelectionRange(0, input.value.length);
    var execOk = document.execCommand('insertText', false, value);

    if (!execOk || input.value !== String(value)) {
      if (nativeSetter) {
        nativeSetter.call(input, value);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }
  }

  function detectControlType(propertyListEl) {
    var compArea = propertyListEl.querySelector('[class*="PropertyFormItem_compArea"]');
    var searchRoot = compArea || propertyListEl;
    if (!compArea && !propertyListEl.querySelector('[data-testid]')) {
      return { type: 'unknown', el: null };
    }

    var datePicker = searchRoot.querySelector('[data-testid="beast-core-datePicker-htmlInput"]');
    if (datePicker) return { type: 'datepicker', el: datePicker };

    var selectWrapper = searchRoot.querySelector('[data-testid="beast-core-select"]');
    if (selectWrapper) {
      var header = selectWrapper.querySelector('[data-testid="beast-core-select-header"]');
      var headerContent = header ? header.querySelector('[class*="ST_selectValueMultiple"]') : null;
      var isMultiple = !!headerContent;
      var input = selectWrapper.querySelector('[data-testid="beast-core-select-htmlInput"]');
      return { type: isMultiple ? 'multi-select' : 'select', el: input, wrapper: selectWrapper, header: header };
    }

    var textInput = searchRoot.querySelector('[data-testid="beast-core-input-htmlInput"]');
    if (textInput) return { type: 'input', el: textInput };

    return { type: 'unknown', el: null };
  }

  function normalizeText(text) {
    return String(text || '').replace(/\s+/g, '').trim();
  }

  function getSingleSelectDisplayValue(wrapper) {
    if (!wrapper) return '';
    var header = wrapper.querySelector('[data-testid="beast-core-select-header"]');
    if (!header) return '';
    var valueRoot = header.querySelector('[class*="ST_selectValueSingle"]');
    if (!valueRoot) return '';
    var text = normalizeText(valueRoot.textContent);
    if (!text || text === normalizeText('请选择')) return '';
    return text;
  }

  function isSelectValueSet(wrapper, value) {
    var current = getSingleSelectDisplayValue(wrapper);
    return !!current && current === normalizeText(value);
  }

  function isMultiSelectValueSet(wrapper, value) {
    if (!wrapper) return false;
    var tags = wrapper.querySelectorAll('[data-testid="beast-core-tagGroup-tag"], [class*="TagGroup_label"], [class*="Tag_"]');
    for (var ti = 0; ti < tags.length; ti++) {
      var tag = tags[ti];
      var textNodes = Array.from(tag.childNodes).filter(function (n) { return n.nodeType === Node.TEXT_NODE; });
      var text = textNodes.map(function (n) { return n.textContent.trim(); }).join('');
      if (normalizeText(text) === normalizeText(value)) return true;
    }
    return false;
  }

  function isElementVisible(el) {
    if (!el || !document.contains(el)) return false;
    var rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) return false;
    var style = window.getComputedStyle(el);
    return style.display !== 'none' && style.visibility !== 'hidden';
  }

  function findPopup() {
    var selectors = [
      '[data-testid="beast-core-select-popup"]',
      '[data-testid*="select-popup"]',
      '[data-testid*="select-list"]',
      '[class*="ST_popup"]',
      '[class*="ST_dropdown"]',
      '[role="listbox"]'
    ];

    for (var si = 0; si < selectors.length; si++) {
      var sel = selectors[si];
      var els = document.querySelectorAll(sel);
      for (var ei = 0; ei < els.length; ei++) {
        if (isElementVisible(els[ei])) return els[ei];
      }
    }

    var bodyChildren = document.body.children;
    for (var bi = bodyChildren.length - 1; bi >= Math.max(0, bodyChildren.length - 20); bi--) {
      var child = bodyChildren[bi];
      if (child.tagName === 'SCRIPT' || child.tagName === 'STYLE' || child.tagName === 'LINK') continue;
      if (!isElementVisible(child)) continue;
      var cs = window.getComputedStyle(child);
      if (cs.position !== 'absolute' && cs.position !== 'fixed') continue;
      if (child.querySelector('[data-testid="beast-core-select-option"], [role="option"], [class*="ST_option"]')) {
        return child;
      }
    }
    return null;
  }

  function simulateClick(el) {
    el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  }

  function findAndClickOption(targetText) {
    var optionSelectors = [
      '[data-testid="beast-core-select-option"]',
      '[class*="ST_option"]',
      '[class*="Option_"]',
      '[role="option"]'
    ];

    for (var si = 0; si < optionSelectors.length; si++) {
      var selector = optionSelectors[si];
      var options = document.querySelectorAll(selector);
      for (var oi = 0; oi < options.length; oi++) {
        var opt = options[oi];
        if (!isElementVisible(opt)) continue;
        if (opt.textContent.trim() === targetText) {
          simulateClick(opt);
          return true;
        }
      }
    }

    var popup = findPopup();
    if (popup) {
      var items = popup.querySelectorAll('div, li, span');
      for (var ii = 0; ii < items.length; ii++) {
        var item = items[ii];
        if (item.children.length > 3) continue;
        var text = item.textContent.trim();
        if (text === targetText && isElementVisible(item)) {
          simulateClick(item);
          return true;
        }
      }
    }

    return false;
  }

  function delay(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  function waitForElement(finder, maxWait, interval) {
    maxWait = maxWait || 3000;
    interval = interval || 100;
    return new Promise(function (resolve) {
      var start = Date.now();
      var check = function () {
        var el = finder();
        if (el) return resolve(el);
        if (Date.now() - start > maxWait) return resolve(null);
        setTimeout(check, interval);
      };
      check();
    });
  }

  function waitForCondition(checker, maxWait, interval) {
    maxWait = maxWait || 1000;
    interval = interval || 80;
    var start = Date.now();
    return new Promise(function (resolve) {
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
    });
  }

  function closeDropdown() {
    document.body.click();
    return delay(150);
  }

  function fillSelect(control, value) {
    var input = control.el;
    var header = control.header;
    var wrapper = control.wrapper;

    if (!input || !header) return Promise.resolve(false);
    if (!document.contains(input)) {
      console.warn('[PDD填充插件] input 元素已从 DOM 脱离，跳过');
      return Promise.resolve(false);
    }

    if (isSelectValueSet(wrapper, value)) {
      console.log('[PDD填充插件] fillSelect("' + value + '") → 已选中，跳过');
      return Promise.resolve(true);
    }

    function tryDirectMatch() {
      simulateClick(header);
      return waitForElement(findPopup, 1500, 80).then(function (popup) {
        if (popup) {
          return delay(100).then(function () {
            if (findAndClickOption(value)) {
              return closeDropdown().then(function () {
                return waitForCondition(function () {
                  return isSelectValueSet(wrapper, value);
                }, 1200, 100);
              }).then(function (success) {
                console.log('[PDD填充插件] fillSelect("' + value + '") → 直接匹配后校验: ' + success);
                return success;
              });
            }
            return false;
          });
        }
        return false;
      });
    }

    function trySearch() {
      console.log('[PDD填充插件] fillSelect("' + value + '") → 直接查找失败，尝试搜索过滤');
      input.focus();
      setInputValue(input, value);
      return delay(500).then(function () {
        return waitForElement(function () {
          return findAndClickOption(value) ? true : null;
        }, 2000, 150);
      }).then(function (clicked) {
        if (clicked) {
          return closeDropdown().then(function () {
            return waitForCondition(function () {
              return isSelectValueSet(wrapper, value);
            }, 1200, 100);
          }).then(function (success) {
            console.log('[PDD填充插件] fillSelect("' + value + '") → 搜索匹配后校验: ' + success);
            return success;
          });
        }
        return false;
      });
    }

    function tryKeyboard() {
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', keyCode: 40, which: 40, bubbles: true }));
      return delay(100).then(function () {
        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, which: 13, bubbles: true }));
        return delay(200);
      }).then(function () {
        return closeDropdown();
      }).then(function () {
        return waitForCondition(function () {
          return isSelectValueSet(wrapper, value);
        }, 1200, 100);
      }).then(function (success) {
        console.log('[PDD填充插件] fillSelect("' + value + '") → 键盘兜底, 验证:' + success);
        return success;
      });
    }

    return tryDirectMatch().then(function (directSuccess) {
      if (directSuccess) return true;
      return trySearch();
    }).then(function (searchSuccess) {
      if (searchSuccess) return true;
      return tryKeyboard();
    });
  }

  function fillMultiSelect(control, value) {
    var input = control.el;
    var header = control.header;
    var wrapper = control.wrapper;

    if (!input || !header) return Promise.resolve(false);
    if (!document.contains(input)) {
      console.warn('[PDD填充插件] input 元素已从 DOM 脱离，跳过');
      return Promise.resolve(false);
    }

    var values = value.split(/\s*\/\s*/).map(function (v) { return v.trim(); }).filter(Boolean);
    var successCount = 0;

    function tryDirectMatch(val) {
      if (findAndClickOption(val)) {
        return waitForCondition(function () {
          return isMultiSelectValueSet(wrapper, val);
        }, 1000, 100).then(function (success) {
          console.log('[PDD填充插件] multiSelect "' + val + '" → 直接匹配后校验: ' + success);
          if (success) successCount++;
          return success;
        });
      }
      return Promise.resolve(false);
    }

    function trySearch(val) {
      console.log('[PDD填充插件] multiSelect "' + val + '" → 直接查找失败，尝试搜索');
      input.focus();
      setInputValue(input, val);
      return delay(400).then(function () {
        return waitForElement(function () {
          return findAndClickOption(val) ? true : null;
        }, 2000, 150);
      }).then(function (clicked) {
        if (clicked) {
          return waitForCondition(function () {
            return isMultiSelectValueSet(wrapper, val);
          }, 1000, 100).then(function (success) {
            console.log('[PDD填充插件] multiSelect "' + val + '" → 搜索匹配后校验: ' + success);
            if (success) successCount++;
            return success;
          });
        } else {
          input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', keyCode: 40, which: 40, bubbles: true }));
          return delay(100).then(function () {
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, which: 13, bubbles: true }));
            return waitForCondition(function () {
              return isMultiSelectValueSet(wrapper, val);
            }, 1000, 100);
          }).then(function (success) {
            if (success) successCount++;
            return success;
          });
        }
      });
    }

    function processValues() {
      return simulateClick(header).then(function () {
        return waitForElement(findPopup, 1500, 80);
      }).then(function (popup) {
        if (popup) return delay(100);
        return null;
      }).then(function () {
        var chain = Promise.resolve();
        var self = this;

        for (var vi = 0; vi < values.length; vi++) {
          var val = values[vi];
          (function (v) {
            chain = chain.then(function () {
              if (isMultiSelectValueSet(wrapper, v)) {
                console.log('[PDD填充插件] multiSelect "' + v + '" → 已选中，跳过');
                successCount++;
                return Promise.resolve();
              }
              return tryDirectMatch(v).then(function (directSuccess) {
                if (directSuccess) return true;
                return trySearch(v);
              }).then(function () {
                return setInputValue(input, '');
              }).then(function () {
                return delay(150);
              });
            });
          })(val);
        }

        return chain;
      }).then(function () {
        return closeDropdown();
      }).then(function () {
        console.log('[PDD填充插件] fillMultiSelect → 成功 ' + successCount + '/' + values.length);
        return successCount > 0;
      });
    }

    return processValues();
  }

  function fillTextInput(control, value) {
    var input = control.el;
    if (!input) return Promise.resolve(false);

    input.focus();
    input.dispatchEvent(new Event('focus', { bubbles: true }));

    return delay(100).then(function () {
      setInputValue(input, value);
      return delay(100);
    }).then(function () {
      input.dispatchEvent(new Event('blur', { bubbles: true }));
      return true;
    });
  }

  function fillOneAttribute(attr, propertyMap) {
    var name = attr.name;
    var value = attr.value;
    if (!name || !value) return Promise.resolve('skip');

    var match = findPropertyEl(name, propertyMap);
    if (!match) {
      Toast.show('填充失败: 属性"' + name + '"未找到', 'error', 3000);
      return Promise.resolve('not-found');
    }

    var control = detectControlType(match.el);
    console.log('[PDD填充插件] ' + name + ' → 类型: ' + control.type + ', 值: ' + value);

    if (control.type === 'select') {
      return fillSelect(control, value).then(function (filled) { return filled ? 'success' : 'failed'; });
    } else if (control.type === 'multi-select') {
      return fillMultiSelect(control, value).then(function (filled) { return filled ? 'success' : 'failed'; });
    } else if (control.type === 'input') {
      return fillTextInput(control, value).then(function (filled) { return filled ? 'success' : 'failed'; });
    } else if (control.type === 'datepicker') {
      console.log('[PDD填充插件] 日期选择器暂不支持自动填充: ' + name);
      return Promise.resolve('skip');
    } else {
      console.warn('[PDD填充插件] 未知控件类型: ' + name);
      return Promise.resolve('skip');
    }
  }

  var _isFillingAttributes = false;

  function fillAttributes(attrArray) {
    if (!Array.isArray(attrArray) || attrArray.length === 0) {
      Toast.show('收到的属性数据为空或格式不正确', 'error');
      return;
    }
    if (_isFillingAttributes) {
      Toast.show('属性填充进行中，已忽略重复触发', 'warning', 3000);
      console.warn('[PDD填充插件] fillAttributes 正在执行，忽略本次重复触发');
      return;
    }
    _isFillingAttributes = true;

    Toast.show('开始填充 ' + attrArray.length + ' 个属性...', 'info', 3000);
    console.log('[PDD填充插件] 开始填充，属性数量:', attrArray.length);

    var pending = attrArray.filter(function (a) { return a.name && a.value; });
    var skippedEmpty = attrArray.length - pending.length;
    var skipCount = skippedEmpty;
    var successCount = 0;
    var failedNames = [];
    var MAX_ROUNDS = 5;
    var round = 0;

    var self = this;

    function runRound() {
      if (pending.length === 0 || round >= MAX_ROUNDS) {
        finalize();
        return;
      }

      round++;
      console.log('[PDD填充插件] === 第 ' + round + ' 轮扫描，待填充: ' + pending.length + ' 个 ===');

      var filledThisRound = 0;
      var stillPending = [];

      var chain = Promise.resolve();
      var self = this;

      for (var pi = 0; pi < pending.length; pi++) {
        var attr = pending[pi];
        (function (a, idx) {
          chain = chain.then(function () {
            var propertyMap = buildPropertyMap();
            if (filledThisRound === 0 && idx === 0) {
              console.log('[PDD填充插件] 当前页面属性:', Array.from(propertyMap.keys()));
            }

            var total = attrArray.length;
            var current = idx + 1;
            var percent = Math.round((current / total) * 100);
            Toast.show('正在填充 (' + current + '/' + total + ', ' + percent + '%): ' + a.name, 'info', 2000);

            return fillOneAttribute(a, propertyMap).then(function (result) {
              if (result === 'success') {
                successCount++;
                filledThisRound++;
                return delay(300);
              } else if (result === 'not-found') {
                stillPending.push(a);
              } else if (result === 'failed') {
                console.warn('[PDD填充插件] ' + a.name + ' 填充失败，将在下一轮重试');
                stillPending.push(a);
              } else {
                skipCount++;
              }
              return delay(200);
            });
          });
        })(attr, pi);
      }

      return chain.then(function () {
        pending.length = 0;
        pending.push.apply(pending, stillPending);

        if (filledThisRound === 0 && pending.length > 0) {
          console.log('[PDD填充插件] 本轮无新进展，等待页面动态渲染...');
          return delay(1500).then(function () {
            var retryMap = buildPropertyMap();
            var finalPending = [];
            var retryChain = Promise.resolve();

            for (var ri = 0; ri < pending.length; ri++) {
              var rAttr = pending[ri];
              (function (ra) {
                retryChain = retryChain.then(function () {
                  return fillOneAttribute(ra, retryMap).then(function (result) {
                    if (result === 'success') {
                      successCount++;
                      return delay(600);
                    } else if (result === 'not-found') {
                      finalPending.push(ra);
                    } else {
                      skipCount++;
                    }
                    return delay(400);
                  });
                });
              })(rAttr);
            }

            return retryChain.then(function () {
              for (var fi = 0; fi < finalPending.length; fi++) {
                failedNames.push(finalPending[fi].name);
                skipCount++;
              }
              finalize();
            });
          });
        } else {
          return runRound();
        }
      });
    }

    function finalize() {
      _isFillingAttributes = false;

      var summaryType = failedNames.length === 0 ? 'success' : 'warning';
      Toast.show('PDD属性填充完成', summaryType, TOAST_LONG_DURATION);
      Toast.show('成功: ' + successCount + ', 跳过: ' + skipCount, 'info', TOAST_LONG_DURATION);

      if (failedNames.length > 0) {
        Toast.show('未匹配属性: ' + failedNames.join(', '), 'error', 8000);
      }

      console.log('[PDD填充插件] PDD属性填充完成');
      console.log('[PDD填充插件] 成功: ' + successCount + ', 跳过: ' + skipCount);
      if (failedNames.length > 0) {
        console.log('[PDD填充插件] 未匹配属性:', failedNames);
      }
    }

    delay(500).then(function () {
      return runRound();
    });
  }

  var _dedupSeen = new Map();

  function stableStringify(value) {
    if (value === null || value === undefined) return String(value);
    if (typeof value !== 'object') return JSON.stringify(value);
    if (Array.isArray(value)) return '[' + value.map(stableStringify).join(',') + ']';
    var keys = Object.keys(value).sort();
    var pairs = keys.map(function (k) { return JSON.stringify(k) + ':' + stableStringify(value[k]); });
    return '{' + pairs.join(',') + '}';
  }

  function dedupCheck(type, data, windowMs) {
    windowMs = windowMs || 2000;
    var now = Date.now();
    var keys = Array.from(_dedupSeen.keys());
    for (var ki = 0; ki < keys.length; ki++) {
      if (now - _dedupSeen.get(keys[ki]) > windowMs) _dedupSeen.delete(keys[ki]);
    }
    var dedupKey = type + ':' + stableStringify(data);
    var hitAt = _dedupSeen.get(dedupKey);
    if (hitAt && now - hitAt <= windowMs) return false;
    _dedupSeen.set(dedupKey, now);
    return true;
  }

  var TRUSTED_ORIGINS = new Set([
    'https://mms.pinduoduo.com',
    'null'
  ]);

  function setupEventListeners(handlers) {
    handlers = handlers || {};
    var fillAttributesHandler = handlers.fillAttributes || fillAttributes;
    var fillTitleHandler = handlers.fillTitle || fillTitle;
    var uploadImagesHandler = handlers.uploadImages;
    var uploadDetailImagesHandler = handlers.uploadDetailImages;
    var uploadSkuImagesHandler = handlers.uploadSkuImages;
    var fillSkuHandler = handlers.fillSku;

    function fillSkuSpecsHandler(data) {
      if (!data || !data.skuAxes) {
        Toast.show('填充失败: 规格数据为空', 'error');
        return;
      }
      if (typeof fillSkuHandler === 'function') {
        fillSkuHandler({ skuAxes: data.skuAxes, skuList: null }, { completionMessage: 'PDD规格类型填充完成' });
      }
    }

    function fillSkuTableHandler(data) {
      if (!data || !data.skus) {
        Toast.show('填充失败: SKU数据为空', 'error');
        return;
      }
      var skuList = null;
      if (data.skus && Array.isArray(data.skus)) {
        skuList = data.skus.map(function (sku) {
          var specValues = {};
          if (sku.specs && Array.isArray(sku.specs)) {
            for (var si = 0; si < sku.specs.length; si++) {
              var s = sku.specs[si];
              specValues[s.key] = s.value;
            }
          }
          return {
            specValues: specValues,
            stock: sku.stock != null ? String(sku.stock) : '',
            groupPrice: sku.price || '',
            singlePrice: sku.marketPrice || '',
            skuCode: sku.productCode || '',
            imageUrl: sku.image || ''
          };
        });
      }
      if (typeof fillSkuHandler === 'function') {
        fillSkuHandler({ skuAxes: null, skuList: skuList, batchFill: data.batchFill }, { completionMessage: 'PDDsku表格填充完成' });
      }
    }

    function clearSkuSpecsHandler() {
      if (window.SkuHandler && window.SkuHandler.clearAllSpecValues) {
        window.SkuHandler.clearAllSpecValues({ delay: delay });
        Toast.show('已清空规格值', 'info', 2000);
      }
    }

    document.addEventListener('pdd-fill-attributes', function (e) {
      var data = e.detail;
      if (!dedupCheck('pdd-fill-attributes', data)) return;
      console.log('[PDD填充插件] [CustomEvent] 收到属性数据:', data);
      if (fillAttributesHandler) fillAttributesHandler(data);
    });

    document.addEventListener('pdd-fill-title', function (e) {
      var data = e.detail;
      if (!dedupCheck('pdd-fill-title', data)) return;
      console.log('[PDD填充插件] [CustomEvent] 收到标题数据:', data);
      if (fillTitleHandler) fillTitleHandler(data);
    });

    if (uploadImagesHandler) {
      document.addEventListener('pdd-upload-images', function (e) {
        var data = e.detail;
        if (!dedupCheck('pdd-upload-images', data)) return;
        console.log('[PDD填充插件] [CustomEvent] 收到图片数据:', data);
        uploadImagesHandler(data);
      });
    }

    if (uploadDetailImagesHandler) {
      document.addEventListener('pdd-upload-detail-images', function (e) {
        var data = e.detail;
        if (!dedupCheck('pdd-upload-detail-images', data)) return;
        console.log('[PDD填充插件] [CustomEvent] 收到详情图数据:', data);
        uploadDetailImagesHandler(data);
      });
    }

    if (uploadSkuImagesHandler) {
      document.addEventListener('pdd-upload-sku-images', function (e) {
        var data = e.detail;
        if (!dedupCheck('pdd-upload-sku-images', data)) return;
        console.log('[PDD填充插件] [CustomEvent] 收到SKU图数据:', data);
        uploadSkuImagesHandler(data);
      });
    }

    if (fillSkuHandler) {
      document.addEventListener('pdd-fill-sku', function (e) {
        var data = e.detail;
        if (!dedupCheck('pdd-fill-sku', data)) return;
        console.log('[PDD填充插件] [CustomEvent] 收到规格库存数据:', data);
        fillSkuHandler(data);
      });
    }

    window.addEventListener('message', function (event) {
      if (event.source !== window) return;
      if (!event.data || !event.data.type) return;

      if (!TRUSTED_ORIGINS.has(event.origin)) {
        console.warn('[PDD填充插件] [postMessage] 拒绝来自未知 origin 的消息:', event.origin);
        return;
      }

      var data = event.data.data;
      var type = event.data.type;

      if (type === 'PDD_FILL_ATTRIBUTES') {
        if (!dedupCheck('pdd-fill-attributes', data)) return;
        if (fillAttributesHandler) fillAttributesHandler(data);
      } else if (type === 'PDD_FILL_TITLE') {
        if (!dedupCheck('pdd-fill-title', data)) return;
        if (fillTitleHandler) fillTitleHandler(data);
      } else if (type === 'PDD_UPLOAD_IMAGES') {
        if (!dedupCheck('pdd-upload-images', data)) return;
        if (uploadImagesHandler) uploadImagesHandler(data);
      } else if (type === 'PDD_UPLOAD_DETAIL_IMAGES') {
        if (!dedupCheck('pdd-upload-detail-images', data)) return;
        if (uploadDetailImagesHandler) uploadDetailImagesHandler(data);
      } else if (type === 'PDD_UPLOAD_SKU_IMAGES') {
        if (!dedupCheck('pdd-upload-sku-images', data)) return;
        if (uploadSkuImagesHandler) uploadSkuImagesHandler(data);
      } else if (type === 'PDD_FILL_SKU') {
        if (!dedupCheck('pdd-fill-sku', data)) return;
        if (fillSkuHandler) fillSkuHandler(data);
      } else if (type === 'PDD_FILL_SKU_SPECS') {
        if (!dedupCheck('pdd-fill-sku-specs', data)) return;
        if (fillSkuSpecsHandler) fillSkuSpecsHandler(data);
      } else if (type === 'PDD_FILL_SKU_TABLE') {
        if (!dedupCheck('pdd-fill-sku-table', data)) return;
        if (fillSkuTableHandler) fillSkuTableHandler(data);
      } else if (type === 'PDD_FILL_SKU_CLEAR') {
        if (!dedupCheck('pdd-fill-sku-clear', data)) return;
        if (clearSkuSpecsHandler) clearSkuSpecsHandler();
      }
    });
  }

  return {
    Toast: Toast,
    extractLabelText: extractLabelText,
    buildPropertyMap: buildPropertyMap,
    findPropertyEl: findPropertyEl,
    findTitleInput: findTitleInput,
    fillTitle: fillTitle,
    detectControlType: detectControlType,
    setInputValue: setInputValue,
    fillOneAttribute: fillOneAttribute,
    fillAttributes: fillAttributes,
    setupEventListeners: setupEventListeners,
    TRUSTED_ORIGINS: TRUSTED_ORIGINS
  };
}));
