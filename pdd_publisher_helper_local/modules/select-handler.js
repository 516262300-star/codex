// select-handler.js - 下拉框处理模块
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.SelectHandler = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  function detectControlType(propertyListEl) {
    var compArea = propertyListEl.querySelector(
      '[class*="PropertyFormItem_compArea"]'
    );
    var searchRoot = compArea || propertyListEl;
    if (!compArea && !propertyListEl.querySelector('[data-testid]')) {
      return { type: 'unknown', el: null };
    }

    var datePicker = searchRoot.querySelector(
      '[data-testid="beast-core-datePicker-htmlInput"]'
    );
    if (datePicker) return { type: 'datepicker', el: datePicker };

    var selectWrapper = searchRoot.querySelector('[data-testid="beast-core-select"]');
    if (selectWrapper) {
      var header = selectWrapper.querySelector('[data-testid="beast-core-select-header"]');
      var headerContent = header ? header.querySelector('[class*="ST_selectValueMultiple"]') : null;
      var isMultiple = !!headerContent;
      var input = selectWrapper.querySelector(
        '[data-testid="beast-core-select-htmlInput"]'
      );
      return { type: isMultiple ? 'multi-select' : 'select', el: input, wrapper: selectWrapper, header: header };
    }

    var textInput = searchRoot.querySelector(
      '[data-testid="beast-core-input-htmlInput"]'
    );
    if (textInput) return { type: 'input', el: textInput };

    return { type: 'unknown', el: null };
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
    var isElementVisible = function (el) {
      if (!el || !document.contains(el)) return false;
      var rect = el.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) return false;
      var style = window.getComputedStyle(el);
      return style.display !== 'none' && style.visibility !== 'hidden';
    };

    for (var s = 0; s < selectors.length; s++) {
      var sel = selectors[s];
      var els = document.querySelectorAll(sel);
      for (var i = 0; i < els.length; i++) {
        if (isElementVisible(els[i])) return els[i];
      }
    }

    var bodyChildren = document.body.children;
    for (var j = bodyChildren.length - 1; j >= Math.max(0, bodyChildren.length - 20); j--) {
      var child = bodyChildren[j];
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

  function findAndClickOption(targetText, simulateClick) {
    simulateClick = simulateClick || function (el) {
      el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
      el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    };

    var isElementVisible = function (el) {
      if (!el || !document.contains(el)) return false;
      var rect = el.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) return false;
      var style = window.getComputedStyle(el);
      return style.display !== 'none' && style.visibility !== 'hidden';
    };

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
    var tags = wrapper.querySelectorAll(
      '[data-testid="beast-core-tagGroup-tag"], [class*="TagGroup_label"], [class*="Tag_"]'
    );
    for (var ti = 0; ti < tags.length; ti++) {
      var tag = tags[ti];
      var textNodes = Array.from(tag.childNodes).filter(function (n) {
        return n.nodeType === Node.TEXT_NODE;
      });
      var text = textNodes.map(function (n) {
        return n.textContent.trim();
      }).join('');
      if (normalizeText(text) === normalizeText(value)) return true;
    }
    return false;
  }

  function closeDropdown(delay) {
    delay = delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };
    document.body.click();
    return delay(150);
  }

  function fillSelect(control, value, options) {
    options = options || {};
    var input = control.el;
    var header = control.header;
    var wrapper = control.wrapper;
    var _delay = options.delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };
    var _setInputValue = options.setInputValue || function () {};
    var _simulateClick = options.simulateClick || function (el) {
      el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
      el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      return Promise.resolve();
    };
    var _findPopup = options.findPopup || findPopup;
    var _findAndClickOption = options.findAndClickOption || findAndClickOption;
    var _isSelectValueSet = options.isSelectValueSet || isSelectValueSet;
    var _waitForElement = options.waitForElement || function (finder, maxWait, interval) {
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
    };
    var _waitForCondition = options.waitForCondition || function (checker, maxWait, interval) {
      maxWait = maxWait || 1000;
      interval = interval || 80;
      var start = Date.now();
      return new Promise(function (resolve) {
        var tick = function () {
          try {
            if (checker()) return resolve(true);
          } catch (e) {}
          if (Date.now() - start <= maxWait) {
            _delay(interval).then(tick);
          } else {
            resolve(false);
          }
        };
        tick();
      });
    };
    var _closeDropdown = options.closeDropdown || closeDropdown;

    if (!input || !header) return Promise.resolve(false);
    if (!document.contains(input)) {
      console.warn('[PDD填充插件] input 元素已从 DOM 脱离，跳过');
      return Promise.resolve(false);
    }

    if (_isSelectValueSet(wrapper, value)) {
      console.log('[PDD填充插件] fillSelect("' + value + '") → 已选中，跳过');
      return Promise.resolve(true);
    }

    var self = this;

    function tryDirectMatch() {
      _simulateClick(header);
      return _waitForElement(_findPopup, 1500, 80).then(function (popup) {
        if (popup) {
          return _delay(100).then(function () {
            if (_findAndClickOption(value)) {
              return _closeDropdown(_delay).then(function () {
                return _waitForCondition(function () {
                  return _isSelectValueSet(wrapper, value);
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
      _setInputValue(input, value);
      return _delay(500).then(function () {
        return _waitForElement(function () {
          return _findAndClickOption(value) ? true : null;
        }, 2000, 150);
      }).then(function (clicked) {
        if (clicked) {
          return _closeDropdown(_delay).then(function () {
            return _waitForCondition(function () {
              return _isSelectValueSet(wrapper, value);
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
      return _delay(100).then(function () {
        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, which: 13, bubbles: true }));
        return _delay(200);
      }).then(function () {
        return _closeDropdown(_delay);
      }).then(function () {
        return _waitForCondition(function () {
          return _isSelectValueSet(wrapper, value);
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

  function fillMultiSelect(control, value, options) {
    options = options || {};
    var input = control.el;
    var header = control.header;
    var wrapper = control.wrapper;
    var _delay = options.delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };
    var _setInputValue = options.setInputValue || function () {};
    var _simulateClick = options.simulateClick || function (el) {
      el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
      el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      return Promise.resolve();
    };
    var _findPopup = options.findPopup || findPopup;
    var _findAndClickOption = options.findAndClickOption || findAndClickOption;
    var _isMultiSelectValueSet = options.isMultiSelectValueSet || isMultiSelectValueSet;
    var _waitForElement = options.waitForElement || function (finder, maxWait, interval) {
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
    };
    var _waitForCondition = options.waitForCondition || function (checker, maxWait, interval) {
      maxWait = maxWait || 1000;
      interval = interval || 80;
      var start = Date.now();
      return new Promise(function (resolve) {
        var tick = function () {
          try {
            if (checker()) return resolve(true);
          } catch (e) {}
          if (Date.now() - start <= maxWait) {
            _delay(interval).then(tick);
          } else {
            resolve(false);
          }
        };
        tick();
      });
    };
    var _closeDropdown = options.closeDropdown || closeDropdown;

    function ensurePromise(value) {
      return value && typeof value.then === 'function' ? value : Promise.resolve(value);
    }

    if (!input || !header) return Promise.resolve(false);
    if (!document.contains(input)) {
      console.warn('[PDD填充插件] input 元素已从 DOM 脱离，跳过');
      return Promise.resolve(false);
    }

    var values = value.split(/\s*\/\s*/).map(function (v) { return v.trim(); }).filter(Boolean);
    var successCount = 0;

    function processValues() {
      return ensurePromise(_simulateClick(header)).then(function () {
        return _waitForElement(_findPopup, 1500, 80);
      }).then(function (popup) {
        if (popup) return _delay(100);
        return null;
      }).then(function () {
        var promises = values.map(function (val) {
          if (_isMultiSelectValueSet(wrapper, val)) {
            console.log('[PDD填充插件] multiSelect "' + val + '" → 已选中，跳过');
            successCount++;
            return Promise.resolve();
          }

          function tryDirect() {
            if (_findAndClickOption(val)) {
              return _waitForCondition(function () {
                return _isMultiSelectValueSet(wrapper, val);
              }, 1000, 100).then(function (success) {
                console.log('[PDD填充插件] multiSelect "' + val + '" → 直接匹配后校验: ' + success);
                if (success) successCount++;
                return success;
              });
            }
            return Promise.resolve(false);
          }

          function trySearch() {
            console.log('[PDD填充插件] multiSelect "' + val + '" → 直接查找失败，尝试搜索');
            input.focus();
            _setInputValue(input, val);
            return _delay(400).then(function () {
              return _waitForElement(function () {
                return _findAndClickOption(val) ? true : null;
              }, 2000, 150);
            }).then(function (clicked) {
              if (clicked) {
                return _waitForCondition(function () {
                  return _isMultiSelectValueSet(wrapper, val);
                }, 1000, 100).then(function (success) {
                  console.log('[PDD填充插件] multiSelect "' + val + '" → 搜索匹配后校验: ' + success);
                  if (success) successCount++;
                  return success;
                });
              } else {
                input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', keyCode: 40, which: 40, bubbles: true }));
                return _delay(100).then(function () {
                  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, which: 13, bubbles: true }));
                  return _waitForCondition(function () {
                    return _isMultiSelectValueSet(wrapper, val);
                  }, 1000, 100);
                }).then(function (success) {
                  if (success) successCount++;
                  return success;
                });
              }
            });
          }

          return tryDirect().then(function (directSuccess) {
            if (directSuccess) return true;
            return trySearch();
          }).then(function () {
            return _setInputValue(input, '');
          }).then(function () {
            return _delay(150);
          });
        });

        return promises.reduce(function (acc, p) {
          return acc.then(function () { return p; });
        }, Promise.resolve());
      }).then(function () {
        return _closeDropdown(_delay);
      }).then(function () {
        console.log('[PDD填充插件] fillMultiSelect → 成功 ' + successCount + '/' + values.length);
        return successCount > 0;
      });
    }

    return processValues();
  }

  return {
    detectControlType: detectControlType,
    findPopup: findPopup,
    findAndClickOption: findAndClickOption,
    getSingleSelectDisplayValue: getSingleSelectDisplayValue,
    isSelectValueSet: isSelectValueSet,
    isMultiSelectValueSet: isMultiSelectValueSet,
    closeDropdown: closeDropdown,
    fillSelect: fillSelect,
    fillMultiSelect: fillMultiSelect
  };
}));