// sku-handler.js - SKU处理模块
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.SkuHandler = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var _isFillingSpecValues = false;

  function findSpecArea() {
    var candidates = ['#stand_spec', '.goods-spec-sku-body', '#goods-spec-sku', '#spec_new'];
    for (var i = 0; i < candidates.length; i++) {
      var sel = candidates[i];
      var el = document.querySelector(sel);
      if (el) return el;
    }

    var allBtns = document.querySelectorAll('button');
    for (var j = 0; j < allBtns.length; j++) {
      var btn = allBtns[j];
      if (btn.textContent.includes('添加规格类型')) {
        return btn.closest('[class*="spec"]') || (btn.parentElement && btn.parentElement.parentElement ? btn.parentElement.parentElement : null);
      }
    }
    return null;
  }

  function findSpecRowContainer(selectWrapper) {
    var known = selectWrapper.closest('.property-container-v2.custom-standard')
      || selectWrapper.closest('.goods-spec-row')
      || selectWrapper.closest('[class*="property-container"]')
      || selectWrapper.closest('[class*="spec-row"]');
    if (known) return known;

    var el = selectWrapper.parentElement;
    while (el && el !== document.body) {
      if (el.tagName === 'DIV' && el.querySelector('input[data-testid="beast-core-input-htmlInput"]:not([readonly])')) {
        return el;
      }
      el = el.parentElement;
    }
    return selectWrapper.parentElement;
  }

  function clickAddSpecTypeButton(options) {
    options = options || {};
    var delay = options.delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };
    var simulateClick = options.simulateClick || function (el) {
      el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
      el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    };
    var waitForElement = options.waitForElement || function (finder, maxWait, interval) {
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

    var specArea = findSpecArea();
    if (!specArea) {
      console.warn('[PDD填充插件] 未找到规格区域');
      if (options && options.Toast) options.Toast.show('填充失败: 规格区域未找到', 'error');
      return Promise.resolve(null);
    }

    var addBtn = null;
    var buttons = specArea.querySelectorAll('button');
    for (var i = 0; i < buttons.length; i++) {
      if (buttons[i].textContent.includes('添加规格类型')) {
        addBtn = buttons[i];
        break;
      }
    }

    if (!addBtn) {
      var selects = specArea.querySelectorAll('[data-testid="beast-core-select"]');
      
      // 策略1: 检查是否有空的规格容器（原有逻辑）
      for (var si = selects.length - 1; si >= 0; si--) {
        var inp = selects[si].querySelector('input');
        if (inp && (!inp.value || inp.value === '')) {
          var container = findSpecRowContainer(selects[si]);
          if (container) {
            console.log('[PDD填充插件] 未找到"添加规格类型"按钮，但发现已有空规格容器，复用之');
            return Promise.resolve(container);
          }
        }
      }
      
      // 策略2: 检查是否有预置的规格类型容器（新逻辑）
      for (var si2 = 0; si2 < selects.length; si2++) {
        var container = findSpecRowContainer(selects[si2]);
        if (container) {
          var specInputs = container.querySelectorAll('.spec-input input[data-testid="beast-core-input-htmlInput"], input[data-testid="beast-core-input-htmlInput"]:not([readonly])');
          if (specInputs.length > 0) {
            console.log('[PDD填充插件] 发现预置规格类型容器，直接复用');
            return Promise.resolve(container);
          }
        }
      }
      
      console.warn('[PDD填充插件] 未找到"添加规格类型"按钮，也没有可用的规格容器，请手动添加规格类型');
      return Promise.resolve(null);
    }

    var existingSelectCount = specArea.querySelectorAll('[data-testid="beast-core-select"]').length;

    simulateClick(addBtn);

    return delay(500).then(function () {
      return waitForElement(function () {
        var allSelects = specArea.querySelectorAll('[data-testid="beast-core-select"]');
        if (allSelects.length > existingSelectCount) {
          for (var i = allSelects.length - 1; i >= 0; i--) {
            var inp = allSelects[i].querySelector('input');
            if (inp && (!inp.value || inp.value === '')) {
              return findSpecRowContainer(allSelects[i]);
            }
          }
          return findSpecRowContainer(allSelects[allSelects.length - 1]);
        }
        return null;
      }, 3000, 150);
    });
  }

  function selectSpecType(container, typeName, options) {
    options = options || {};
    var delay = options.delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };
    var fillSelect = options.fillSelect;
    var isSelectValueSet = options.isSelectValueSet || function (wrapper, value) {
      var header = wrapper.querySelector('[data-testid="beast-core-select-header"]');
      if (!header) return '';
      var valueRoot = header.querySelector('[class*="ST_selectValueSingle"]');
      if (!valueRoot) return '';
      var text = String(valueRoot.textContent || '').replace(/\s+/g, '').trim();
      return !!text && text === String(value || '').replace(/\s+/g, '').trim();
    };

    var selectWrapper = container.querySelector('[data-testid="beast-core-select"]');
    if (!selectWrapper) {
      console.warn('[PDD填充插件] 规格容器内未找到 select 组件');
      return Promise.resolve(false);
    }

    var header = selectWrapper.querySelector('[data-testid="beast-core-select-header"]');
    var input = selectWrapper.querySelector('[data-testid="beast-core-select-htmlInput"]');
    if (!header || !input) return Promise.resolve(false);

    if (isSelectValueSet(selectWrapper, typeName)) {
      console.log('[PDD填充插件] 规格类型已选中: ' + typeName);
      return Promise.resolve(true);
    }

    var control = { el: input, header: header, wrapper: selectWrapper };
    var self = this;

    function doFill() {
      if (fillSelect) {
        return fillSelect(control, typeName).then(function (result) {
          if (result) {
            console.log('[PDD填充插件] 规格类型选择成功: ' + typeName);
            return delay(500).then(function () { return true; });
          }
          return false;
        });
      }
      return Promise.resolve(false);
    }

    return doFill();
  }

  function fillSpecValues(container, values, options) {
    if (_isFillingSpecValues) {
      console.warn('[PDD填充插件] 规格值填充进行中，忽略重复请求');
      return Promise.resolve(0);
    }
    _isFillingSpecValues = true;

    options = options || {};
    var delay = options.delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };

    var filledCount = 0;

    function waitForDomStable(maxWait) {
      maxWait = maxWait || 5000;
      return new Promise(function (resolve) {
        var start = Date.now();
        var lastCount = 0;
        var stableCount = 0;

        var observer = new MutationObserver(function () {
          var currentCount = container.querySelectorAll('.spec-input').length;
          if (currentCount === lastCount) {
            stableCount++;
            if (stableCount >= 3) {
              clearTimeout(timer);
              observer.disconnect();
              resolve(true);
            }
          } else {
            stableCount = 0;
          }
          lastCount = currentCount;
        });

        observer.observe(container, { childList: true, subtree: true });

        var timer = setTimeout(function () {
          observer.disconnect();
          resolve(false);
        }, maxWait);
      });
    }

    function clearAllSpecValues() {
      var deleteButtons = container.querySelectorAll('.delete-btn a[data-testid="beast-core-button-link"]');
      if (deleteButtons.length === 0) {
        console.log('[PDD填充插件] 无需清空现有规格值');
        return Promise.resolve();
      }
      console.log('[PDD填充插件] 清空 ' + deleteButtons.length + ' 个现有规格值...');

      function clickOne(index) {
        if (index >= deleteButtons.length) return Promise.resolve();
        var btn = deleteButtons[index];
        btn.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        btn.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
        btn.dispatchEvent(new Event('click', { bubbles: true }));
        return delay(800).then(function () { return clickOne(index + 1); });
      }

      return clickOne(0).then(function () {
        return waitForDomStable(3000);
      }).then(function () {
        return delay(1000);
      });
    }

    function findEmptyInput() {
      return new Promise(function (resolve) {
        var maxWait = 5000;
        var interval = 200;
        var start = Date.now();

        function check() {
          var inputs = container.querySelectorAll('input[data-testid="beast-core-input-htmlInput"]');
          for (var j = 0; j < inputs.length; j++) {
            var inp = inputs[j];
            if (!inp.readOnly && inp.value === '' && !inp.closest('[data-testid="beast-core-select"]')) {
              resolve(inp);
              return;
            }
          }
          if (Date.now() - start > maxWait) {
            resolve(null);
            return;
          }
          setTimeout(check, interval);
        }
        check();
      });
    }

    function verifyValue(value) {
      return new Promise(function (resolve) {
        var maxWait = 3000;
        var interval = 200;
        var start = Date.now();

        function check() {
          var inputs = container.querySelectorAll('input[data-testid="beast-core-input-htmlInput"]');
          var found = false;
          var allValues = [];
          
          for (var i = 0; i < inputs.length; i++) {
            var inp = inputs[i];
            if (!inp.readOnly && !inp.closest('[data-testid="beast-core-select"]')) {
              allValues.push(inp.value.trim());
              if (inp.value.trim() === value.trim()) {
                found = true;
                break;
              }
            }
          }
          
          if (found) {
            console.log('[PDD填充插件] 验证通过，找到值: "' + value + '"');
            resolve(true);
            return;
          }
          
          if (Date.now() - start > maxWait) {
            console.warn('[PDD填充插件] 验证超时，目标值: "' + value + '"，当前所有规格值: [' + allValues.join(', ') + ']');
            resolve(false);
            return;
          }
          
          setTimeout(check, interval);
        }
        check();
      });
    }

    function fillOneValue(val, index, total, retryCount) {
      retryCount = retryCount || 0;
      var maxRetries = 3;
      
      console.log('[PDD填充插件] 填充规格值 ' + (index + 1) + '/' + total + ': "' + val + '"' + (retryCount > 0 ? ' (重试 ' + retryCount + ')' : ''));

      return findEmptyInput().then(function (input) {
        if (!input) {
          console.warn('[PDD填充插件] 找不到空输入框');
          return false;
        }

        input.focus();
        var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        if (nativeSetter) {
          var tracker = input._valueTracker;
          if (tracker) tracker.setValue('');
          nativeSetter.call(input, '');
          input.dispatchEvent(new Event('input', { bubbles: true }));
        }

        return delay(150).then(function () {
          input.setSelectionRange(0, input.value.length);
          document.execCommand('insertText', false, val);
          input.dispatchEvent(new Event('input', { bubbles: true }));
          return delay(800);
        }).then(function () {
          if (input.value.trim() !== val.trim()) {
            console.warn('[PDD填充插件] 值在 blur 前已被重置: "' + val + '"，当前值: "' + input.value.trim() + '"');
            if (nativeSetter) {
              nativeSetter.call(input, val);
              input.dispatchEvent(new Event('input', { bubbles: true }));
            }
            return delay(500);
          }
          return Promise.resolve();
        }).then(function () {
          input.dispatchEvent(new Event('blur', { bubbles: true }));
          return delay(800);
        }).then(function () {
          return verifyValue(val);
        }).then(function (ok) {
          if (ok) {
            console.log('[PDD填充插件] 规格值 "' + val + '" 填充成功');
            return true;
          } else {
            console.warn('[PDD填充插件] 规格值 "' + val + '" 验证失败');
            if (retryCount < maxRetries) {
              console.log('[PDD填充插件] 准备重试填充: "' + val + '"');
              return delay(1000).then(function () {
                return fillOneValue(val, index, total, retryCount + 1);
              });
            }
            return false;
          }
        });
      });
    }

    function fillAllValues() {
      if (!values || values.length === 0) {
        console.warn('[PDD填充插件] 规格值列表为空');
        return Promise.resolve(0);
      }

      return values.reduce(function (promise, val, index) {
        return promise.then(function () {
          return fillOneValue(val, index, values.length);
        }).then(function (success) {
          if (success) filledCount++;
          return delay(1200);
        });
      }, Promise.resolve()).then(function () {
        return filledCount;
      });
    }

    return clearAllSpecValues().then(function () {
      return fillAllValues();
    }).then(function (count) {
      _isFillingSpecValues = false;
      console.log('[PDD填充插件] 规格值填充完成: ' + count + '/' + values.length);
      return count;
    }).catch(function (err) {
      _isFillingSpecValues = false;
      console.error('[PDD填充插件] 规格值填充异常:', err);
      return 0;
    });
  }

  function findExistingSpecContainer(typeName) {
    var specArea = findSpecArea();
    if (!specArea) return null;

    var selects = specArea.querySelectorAll('[data-testid="beast-core-select"]');
    var isSelectValueSet = function (wrapper, value) {
      var header = wrapper.querySelector('[data-testid="beast-core-select-header"]');
      if (!header) return '';
      var valueRoot = header.querySelector('[class*="ST_selectValueSingle"]');
      if (!valueRoot) return '';
      var text = String(valueRoot.textContent || '').replace(/\s+/g, '').trim();
      return !!text && text === String(value || '').replace(/\s+/g, '').trim();
    };

    for (var i = 0; i < selects.length; i++) {
      if (isSelectValueSet(selects[i], typeName)) {
        return findSpecRowContainer(selects[i]);
      }
    }
    return null;
  }

  function fillAllSpecTypes(specTypes, options) {
    options = options || {};
    var delay = options.delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };
    var Toast = options.Toast;
    var clickAddSpecTypeButtonFn = options.clickAddSpecTypeButton || clickAddSpecTypeButton;
    var selectSpecTypeFn = options.selectSpecType || selectSpecType;
    var fillSpecValuesFn = options.fillSpecValues || fillSpecValues;

    function getSelectValue(wrapper) {
      var header = wrapper.querySelector('[data-testid="beast-core-select-header"]');
      if (!header) return '';
      var valueRoot = header.querySelector('[class*="ST_selectValueSingle"]');
      if (!valueRoot) return '';
      return String(valueRoot.textContent || '').replace(/\s+/g, '').trim();
    }

    var totalFilled = 0;
    var self = this;

    function processSpecType(index) {
      if (index >= specTypes.length) return Promise.resolve(totalFilled);

      var spec = specTypes[index];
      var typeName = spec.typeName || spec.name;
      var values = spec.values;
      if (!typeName || !values || values.length === 0) {
        return processSpecType(index + 1);
      }

      if (Toast) Toast.show('正在添加规格类型 (' + (index + 1) + '/' + specTypes.length + '): ' + typeName, 'info', 2000);

      var container = findExistingSpecContainer(typeName);

      function afterContainerFound() {
        if (!container) {
          return clickAddSpecTypeButtonFn({ delay: delay }).then(function (newContainer) {
            if (!newContainer) {
              console.error('[PDD填充插件] 无法添加规格类型: ' + typeName);
              if (Toast) Toast.show('添加规格类型失败: ' + typeName, 'error');
              return processSpecType(index + 1);
            }

            var selectWrapper = newContainer.querySelector('[data-testid="beast-core-select"]');
            var currentType = selectWrapper ? getSelectValue(selectWrapper) : '';

            if (currentType && currentType === typeName) {
              console.log('[PDD填充插件] 预置规格类型已匹配: ' + typeName + '，直接填充规格值');
              if (Toast) Toast.show('正在填充 ' + typeName + ' 的 ' + values.length + ' 个规格值 (' + (index + 1) + '/' + specTypes.length + ')...', 'info', 2000);
              return fillSpecValuesFn(newContainer, values, { delay: delay, typeLikeHuman: options.typeLikeHuman }).then(function (filled) {
                totalFilled += filled;
                console.log('[PDD填充插件] ' + typeName + ': 填充了 ' + filled + '/' + values.length + ' 个规格值');
                return delay(800).then(function () { return processSpecType(index + 1); });
              });
            }

            return selectSpecTypeFn(newContainer, typeName, { delay: delay, fillSelect: options.fillSelect }).then(function (selected) {
              if (!selected) {
                console.error('[PDD填充插件] 无法选择规格类型: ' + typeName);
                if (Toast) Toast.show('选择规格类型失败: ' + typeName, 'error');
                return processSpecType(index + 1);
              }

              if (Toast) Toast.show('正在填充 ' + typeName + ' 的 ' + values.length + ' 个规格值 (' + (index + 1) + '/' + specTypes.length + ')...', 'info', 2000);
              return fillSpecValuesFn(newContainer, values, { delay: delay, typeLikeHuman: options.typeLikeHuman }).then(function (filled) {
                totalFilled += filled;
                console.log('[PDD填充插件] ' + typeName + ': 填充了 ' + filled + '/' + values.length + ' 个规格值');
                return delay(800).then(function () { return processSpecType(index + 1); });
              });
            });
          });
        } else {
          if (Toast) Toast.show('正在填充 ' + typeName + ' 的 ' + values.length + ' 个规格值 (' + (index + 1) + '/' + specTypes.length + ')...', 'info', 2000);
          return fillSpecValuesFn(container, values, { delay: delay, typeLikeHuman: options.typeLikeHuman }).then(function (filled) {
            totalFilled += filled;
            console.log('[PDD填充插件] ' + typeName + ': 填充了 ' + filled + '/' + values.length + ' 个规格值');
            return delay(800).then(function () { return processSpecType(index + 1); });
          });
        }
      }

      return Promise.resolve().then(afterContainerFound);
    }

    return processSpecType(0);
  }

  function fillSkuBatch(batchFill, options) {
    options = options || {};
    var delay = options.delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };
    var setInputValue = options.setInputValue || function () {};
    var simulateClick = options.simulateClick || function (el) {
      el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
      el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    };
    var waitForElement = options.waitForElement || function (finder, maxWait, interval) {
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

    var stock = batchFill.stock;
    var groupPrice = batchFill.groupPrice;
    var singlePrice = batchFill.singlePrice;
    var skuCode = batchFill.skuCode;

    return waitForElement(function () {
      return document.querySelector('.sku-list.list table tbody tr');
    }, 5000, 200).then(function (skuTable) {
      if (!skuTable) {
        console.warn('[PDD填充插件] SKU 表格未出现');
        return Promise.resolve(false);
      }

      var batchWrap = document.querySelector('.sku-batch .batch-wrap');
      if (!batchWrap) {
        console.warn('[PDD填充插件] 未找到批量设置区域 .batch-wrap');
        return Promise.resolve(false);
      }

      function fillStock() {
        if (!stock) return Promise.resolve();
        var stockInput = batchWrap.querySelector('.batch-set.quantity input[data-testid="beast-core-input-htmlInput"]');
        if (stockInput) {
          stockInput.focus();
          setInputValue(stockInput, stock);
          stockInput.dispatchEvent(new Event('blur', { bubbles: true }));
          return delay(200).then(function () {
            console.log('[PDD填充插件] 批量库存已填充: ' + stock);
          });
        }
      }

      function fillGroupPrice() {
        if (!groupPrice) return Promise.resolve();
        var priceInputs = batchWrap.querySelectorAll('.beast-batch-input-price input[data-testid="beast-core-inputNumber-htmlInput"]');
        var groupInput = priceInputs[0];
        if (groupInput) {
          groupInput.focus();
          setInputValue(groupInput, groupPrice);
          groupInput.dispatchEvent(new Event('blur', { bubbles: true }));
          return delay(200).then(function () {
            console.log('[PDD填充插件] 批量拼单价已填充: ' + groupPrice);
          });
        }
      }

      function fillSinglePrice() {
        if (!singlePrice) return Promise.resolve();
        var priceInputs = batchWrap.querySelectorAll('.beast-batch-input-price input[data-testid="beast-core-inputNumber-htmlInput"]');
        var singleInput = priceInputs[1];
        if (singleInput) {
          singleInput.focus();
          setInputValue(singleInput, singlePrice);
          singleInput.dispatchEvent(new Event('blur', { bubbles: true }));
          return delay(200).then(function () {
            console.log('[PDD填充插件] 批量单买价已填充: ' + singlePrice);
          });
        }
      }

      function fillSkuCode() {
        if (!skuCode) return Promise.resolve();
        var codeInputs = batchWrap.querySelectorAll('.batch-set input[data-testid="beast-core-input-htmlInput"]');
        for (var ci = 0; ci < codeInputs.length; ci++) {
          if (codeInputs[ci].placeholder === '规格编码') {
            codeInputs[ci].focus();
            setInputValue(codeInputs[ci], skuCode);
            codeInputs[ci].dispatchEvent(new Event('blur', { bubbles: true }));
            return delay(200).then(function () {
              console.log('[PDD填充插件] 批量规格编码已填充: ' + skuCode);
            });
          }
        }
      }

      return fillStock().then(fillGroupPrice).then(fillSinglePrice).then(fillSkuCode).then(function () {
        return delay(300);
      }).then(function () {
        var batchBtn = batchWrap.querySelector('button[data-testid="beast-core-button"]');
        if (batchBtn && !batchBtn.disabled) {
          simulateClick(batchBtn);
          return delay(500).then(function () {
            console.log('[PDD填充插件] 已点击批量设置按钮');
            return true;
          });
        } else {
          return waitForElement(function () {
            var btn = batchWrap.querySelector('button[data-testid="beast-core-button"]');
            return (btn && !btn.disabled) ? btn : null;
          }, 2000, 200).then(function (enabledBtn) {
            if (enabledBtn) {
              simulateClick(enabledBtn);
              return delay(500).then(function () {
                console.log('[PDD填充插件] 已点击批量设置按钮（等待后）');
                return true;
              });
            }
            console.warn('[PDD填充插件] 批量设置按钮不可点击');
            return false;
          });
        }
      });
    });
  }

  function identifyTdRole(td) {
    if (td.classList.contains('quantity') || td.querySelector('.quantity')) {
      return 'stock';
    }
    if (td.querySelector('.sku-beast-price-input-container')) {
      return 'price';
    }
    if (td.classList.contains('sku-preview-cell') || td.querySelector('input[type="file"]')) {
      return 'preview';
    }
    if (td.querySelector('.sku-row-spec')) {
      return 'specCol';
    }
    if (td.querySelector('.sku-status-word') || td.querySelector('[data-testid="beast-core-switch"]')) {
      return 'status';
    }
    if (td.querySelector('input[data-testid="beast-core-input-htmlInput"]')) {
      return 'skuCode';
    }
    return 'unknown';
  }

  function fillSkuRows(skuList, options) {
    options = options || {};
    var delay = options.delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };
    var setInputValue = options.setInputValue || function () {};
    var fetchImageDirect = options.fetchImageDirect || function () { return Promise.resolve(null); };
    var cleanImageUrl = options.cleanImageUrl || function (url) { return url; };

    var waitForElement = options.waitForElement || function (finder, maxWait, interval) {
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

    return waitForElement(function () {
      return document.querySelector('.sku-list.list table tbody tr');
    }, 5000, 200).then(function () {
      var rows = document.querySelectorAll('.sku-list.list table tbody tr');
      if (rows.length === 0) {
        console.warn('[PDD填充插件] SKU 表格无数据行');
        return 0;
      }

      var firstRowTds = rows[0].querySelectorAll('td');
      var specColCount = 0;
      for (var ti = 0; ti < firstRowTds.length; ti++) {
        if (identifyTdRole(firstRowTds[ti]) === 'specCol') specColCount++;
      }

      var currentSpecValues = [];
      for (var sci = 0; sci < specColCount; sci++) currentSpecValues.push('');
      var rowspanRemaining = [];
      for (var ri = 0; ri < specColCount; ri++) rowspanRemaining.push(0);
      var rowSpecMap = [];

      for (var ri2 = 0; ri2 < rows.length; ri2++) {
        var row = rows[ri2];
        var tds = row.querySelectorAll('td');
        var specTdIdx = 0;

        for (var colIdx = 0; colIdx < specColCount; colIdx++) {
          if (rowspanRemaining[colIdx] > 0) {
            rowspanRemaining[colIdx]--;
          } else {
            var found = false;
            while (specTdIdx < tds.length) {
              if (identifyTdRole(tds[specTdIdx]) === 'specCol') {
                var titleEl = tds[specTdIdx].querySelector('.sku-row-spec .sku-row-title');
                currentSpecValues[colIdx] = titleEl ? titleEl.textContent.trim() : '';
                var rs = parseInt(tds[specTdIdx].getAttribute('rowspan')) || 1;
                rowspanRemaining[colIdx] = rs - 1;
                specTdIdx++;
                found = true;
                break;
              }
              specTdIdx++;
            }
            if (!found) currentSpecValues[colIdx] = '';
          }
        }

        rowSpecMap.push({ row: row, specTexts: currentSpecValues.slice() });
      }

      var filledCount = 0;
      var self = this;

      function processSku(index) {
        if (index >= skuList.length) return Promise.resolve(filledCount);

        var skuItem = skuList[index];
        var specValues = skuItem.specValues;
        var stock = skuItem.stock;
        var groupPrice = skuItem.groupPrice;
        var singlePrice = skuItem.singlePrice;
        var skuCode = skuItem.skuCode;
        var imageUrl = skuItem.imageUrl;

        var targetRow = null;
        if (specValues) {
          var specVals = Object.values(specValues);
          for (var mi = 0; mi < rowSpecMap.length; mi++) {
            var rowData = rowSpecMap[mi];
            var allMatch = specVals.every(function (v) {
              return rowData.specTexts.includes(v);
            });
            if (allMatch) {
              targetRow = rowData.row;
              break;
            }
          }
        } else if (rows.length === 1) {
          targetRow = rows[0];
        }

        if (!targetRow) {
          console.warn('[PDD填充插件] 未找到匹配的 SKU 行:', specValues);
          return processSku(index + 1);
        }

        var tds = targetRow.querySelectorAll('td');
        var priceIndex = 0;

        if (options.Toast) {
          var skuTotal = skuList.length;
          var skuCurrent = index + 1;
          var skuPercent = Math.round((skuCurrent / skuTotal) * 100);
          options.Toast.show('正在填充 SKU (' + skuCurrent + '/' + skuTotal + ', ' + skuPercent + '%): ' + (specValues ? Object.values(specValues).join(', ') : '默认'), 'info', 1500);
        }

        // 等待SKU预览图上传完成（进度条消失）
        function waitForSkuImageUploadComplete(row) {
          var maxWait = 20000;
          var interval = 500;
          var start = Date.now();

          return new Promise(function (resolve) {
            function check() {
              var previewCell = null;
              var rowTds = row.querySelectorAll('td');
              for (var i = 0; i < rowTds.length; i++) {
                if (identifyTdRole(rowTds[i]) === 'preview') {
                  previewCell = rowTds[i];
                  break;
                }
              }

              if (!previewCell) { resolve(); return; }

              // 检测进度条/加载指示器
              var hasProgress = previewCell.querySelector(
                '[class*="progress"], [class*="Progress"], [class*="loading"], [class*="Loading"], ' +
                '[class*="uploading"], [class*="Uploading"], [class*="percent"], [class*="Percent"], ' +
                '[class*="Spn_spinning"], [class*="spin"]'
              );

              if (!hasProgress || Date.now() - start > maxWait) {
                resolve();
                return;
              }

              setTimeout(check, interval);
            }
            // 延迟1秒开始检测，让上传先启动
            setTimeout(check, 1000);
          });
        }

        // 重新填充规格编码（图片上传完成后React重渲染可能清空）
        function refillSkuCode(row) {
          if (!skuCode) return Promise.resolve();
          // 重新获取该行的td（可能被React重建）
          var rowTds = row.querySelectorAll('td');
          for (var i = 0; i < rowTds.length; i++) {
            if (identifyTdRole(rowTds[i]) === 'skuCode') {
              var inp = rowTds[i].querySelector('input[data-testid="beast-core-input-htmlInput"]');
              if (inp && inp.value.trim() !== String(skuCode).trim()) {
                console.log('[PDD填充插件] 图片上传后重新填充规格编码: ' + skuCode);
                inp.focus();
                setInputValue(inp, skuCode);
                inp.dispatchEvent(new Event('blur', { bubbles: true }));
                return delay(200);
              }
              break;
            }
          }
          return Promise.resolve();
        }

        function processTd(tdIndex) {
          if (tdIndex >= tds.length) {
            filledCount++;
            console.log('[PDD填充插件] SKU 行填充完成:', specValues);

            // 如果该行有图片上传且有规格编码，等待上传完成后重新填充规格编码
            if (imageUrl && skuCode) {
              console.log('[PDD填充插件] 等待SKU图片上传完成后重新确认规格编码...');
              return waitForSkuImageUploadComplete(targetRow).then(function () {
                // 图片上传完成后额外等待React重渲染
                return delay(1000);
              }).then(function () {
                return refillSkuCode(targetRow);
              }).then(function () {
                return processSku(index + 1);
              });
            }

            return processSku(index + 1);
          }

          var td = tds[tdIndex];
          var role = identifyTdRole(td);

          function fillStock() {
            if (!stock) return Promise.resolve();
            var inp = td.querySelector('input[data-testid="beast-core-input-htmlInput"]');
            if (inp) {
              inp.focus();
              setInputValue(inp, stock);
              inp.dispatchEvent(new Event('blur', { bubbles: true }));
              return delay(150);
            }
          }

          function fillPrice() {
            var priceVal = priceIndex === 0 ? groupPrice : singlePrice;
            priceIndex++;
            if (!priceVal) return Promise.resolve();
            var inp = td.querySelector('input[data-testid="beast-core-inputNumber-htmlInput"]');
            if (inp) {
              inp.focus();
              setInputValue(inp, priceVal);
              inp.dispatchEvent(new Event('blur', { bubbles: true }));
              return delay(150);
            }
          }

          function fillPreview() {
            if (!imageUrl) return Promise.resolve();
            var fileInput = td.querySelector('input[type="file"][accept*="image"]');
            if (!fileInput) return Promise.resolve();
            return fetchImageDirect(cleanImageUrl(imageUrl)).then(function (imgResult) {
              if (!imgResult) return;
              var ext = imgResult.mimeType === 'image/png' ? 'png' : 'jpg';
              var file = new File([imgResult.blob], 'sku_preview.' + ext, { type: imgResult.mimeType });
              var dt = new DataTransfer();
              dt.items.add(file);
              fileInput.files = dt.files;
              fileInput.dispatchEvent(new Event('change', { bubbles: true }));
              return delay(300);
            });
          }

          function fillSkuCode() {
            if (!skuCode) return Promise.resolve();
            var inp = td.querySelector('input[data-testid="beast-core-input-htmlInput"]');
            if (inp) {
              inp.focus();
              setInputValue(inp, skuCode);
              inp.dispatchEvent(new Event('blur', { bubbles: true }));
              return delay(150);
            }
          }

          var action;
          switch (role) {
            case 'stock': action = fillStock(); break;
            case 'price': action = fillPrice(); break;
            case 'preview': action = fillPreview(); break;
            case 'skuCode': action = fillSkuCode(); break;
            default: action = Promise.resolve();
          }

          return action.then(function () { return processTd(tdIndex + 1); });
        }

        return processTd(0);
      }

      return processSku(0);
    });
  }

  function fillSkuRowsVirtual(skuList, options) {
    options = options || {};
    var delay = options.delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };
    var setInputValue = options.setInputValue || function () {};
    var fetchImageDirect = options.fetchImageDirect || function () { return Promise.resolve(null); };
    var cleanImageUrl = options.cleanImageUrl || function (url) { return url; };
    var waitForElement = options.waitForElement || function (finder, maxWait, interval) {
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

    function skuEntryKey(specVals, index) {
      return specVals && specVals.length ? specVals.join('\u001f') : ('__default_' + index);
    }

    function getRows() {
      return Array.prototype.slice.call(document.querySelectorAll('.sku-list.list table tbody tr'));
    }

    function getSpecColCount(rows) {
      if (!rows.length) return 0;
      var firstRowTds = rows[0].querySelectorAll('td');
      var count = 0;
      for (var ti = 0; ti < firstRowTds.length; ti++) {
        if (identifyTdRole(firstRowTds[ti]) === 'specCol') count++;
      }
      return count || 1;
    }

    function buildVisibleRowSpecMap() {
      var rows = getRows();
      var specColCount = getSpecColCount(rows);
      var currentSpecValues = [];
      var rowspanRemaining = [];
      var rowSpecMap = [];

      for (var sci = 0; sci < specColCount; sci++) currentSpecValues.push('');
      for (var ri = 0; ri < specColCount; ri++) rowspanRemaining.push(0);

      for (var ri2 = 0; ri2 < rows.length; ri2++) {
        var row = rows[ri2];
        var tds = row.querySelectorAll('td');
        var specTdIdx = 0;

        for (var colIdx = 0; colIdx < specColCount; colIdx++) {
          if (rowspanRemaining[colIdx] > 0) {
            rowspanRemaining[colIdx]--;
          } else {
            var found = false;
            while (specTdIdx < tds.length) {
              if (identifyTdRole(tds[specTdIdx]) === 'specCol') {
                var titleEl = tds[specTdIdx].querySelector('.sku-row-spec .sku-row-title');
                currentSpecValues[colIdx] = titleEl ? titleEl.textContent.trim() : '';
                var rs = parseInt(tds[specTdIdx].getAttribute('rowspan')) || 1;
                rowspanRemaining[colIdx] = rs - 1;
                specTdIdx++;
                found = true;
                break;
              }
              specTdIdx++;
            }
            if (!found) currentSpecValues[colIdx] = '';
          }
        }
        rowSpecMap.push({ row: row, specTexts: currentSpecValues.slice() });
      }
      return rowSpecMap;
    }

    function findSkuScrollContainer() {
      var skuRoot = document.querySelector('.sku-list.list') || document.querySelector('#sku') || document.body;
      var nodes = Array.prototype.slice.call(skuRoot.querySelectorAll('*'));
      nodes.unshift(skuRoot);
      for (var i = 0; i < nodes.length; i++) {
        var node = nodes[i];
        if (node.scrollHeight > node.clientHeight + 20) {
          var style = window.getComputedStyle(node);
          if (/(auto|scroll)/.test(style.overflowY + style.overflow)) return node;
        }
      }
      return null;
    }

    function fillOneVisibleRow(skuEntry, targetRow, filledCountRef, total) {
      var skuItem = skuEntry.item;
      var specValues = skuItem.specValues;
      var stock = skuItem.stock;
      var groupPrice = skuItem.groupPrice;
      var singlePrice = skuItem.singlePrice;
      var skuCode = skuItem.skuCode;
      var imageUrl = skuItem.imageUrl;
      var priceIndex = 0;

      if (options.Toast) {
        var skuCurrent = filledCountRef.count + 1;
        var skuPercent = Math.round((skuCurrent / total) * 100);
        options.Toast.show('正在填充 SKU (' + skuCurrent + '/' + total + ', ' + skuPercent + '%): ' + (specValues ? Object.values(specValues).join(', ') : '默认'), 'info', 1500);
      }

      function waitForSkuImageUploadComplete(row) {
        var maxWait = 20000;
        var interval = 500;
        var start = Date.now();
        return new Promise(function (resolve) {
          function check() {
            var previewCell = null;
            var rowTds = row.querySelectorAll('td');
            for (var i = 0; i < rowTds.length; i++) {
              if (identifyTdRole(rowTds[i]) === 'preview') {
                previewCell = rowTds[i];
                break;
              }
            }
            if (!previewCell) { resolve(); return; }
            var hasProgress = previewCell.querySelector(
              '[class*="progress"], [class*="Progress"], [class*="loading"], [class*="Loading"], ' +
              '[class*="uploading"], [class*="Uploading"], [class*="percent"], [class*="Percent"], ' +
              '[class*="Spn_spinning"], [class*="spin"]'
            );
            if (!hasProgress || Date.now() - start > maxWait) {
              resolve();
              return;
            }
            setTimeout(check, interval);
          }
          setTimeout(check, 1000);
        });
      }

      function refillSkuCode(row) {
        if (!skuCode) return Promise.resolve();
        var rowTds = row.querySelectorAll('td');
        for (var i = 0; i < rowTds.length; i++) {
          if (identifyTdRole(rowTds[i]) === 'skuCode') {
            var inp = rowTds[i].querySelector('input[data-testid="beast-core-input-htmlInput"]');
            if (inp && inp.value.trim() !== String(skuCode).trim()) {
              inp.focus();
              setInputValue(inp, skuCode);
              inp.dispatchEvent(new Event('blur', { bubbles: true }));
              return delay(200);
            }
            break;
          }
        }
        return Promise.resolve();
      }

      function processTd(tdIndex) {
        var tds = targetRow.querySelectorAll('td');
        if (tdIndex >= tds.length) {
          filledCountRef.count++;
          if (imageUrl && skuCode) {
            return waitForSkuImageUploadComplete(targetRow).then(function () {
              return delay(1000);
            }).then(function () {
              return refillSkuCode(targetRow);
            });
          }
          return Promise.resolve();
        }

        var td = tds[tdIndex];
        var role = identifyTdRole(td);

        function fillStock() {
          if (!stock) return Promise.resolve();
          var inp = td.querySelector('input[data-testid="beast-core-input-htmlInput"]');
          if (inp) {
            inp.focus();
            setInputValue(inp, stock);
            inp.dispatchEvent(new Event('blur', { bubbles: true }));
            return delay(150);
          }
          return Promise.resolve();
        }

        function fillPrice() {
          var priceVal = priceIndex === 0 ? groupPrice : singlePrice;
          priceIndex++;
          if (!priceVal) return Promise.resolve();
          var inp = td.querySelector('input[data-testid="beast-core-inputNumber-htmlInput"]');
          if (inp) {
            inp.focus();
            setInputValue(inp, priceVal);
            inp.dispatchEvent(new Event('blur', { bubbles: true }));
            return delay(150);
          }
          return Promise.resolve();
        }

        function fillPreview() {
          if (!imageUrl) return Promise.resolve();
          var fileInput = td.querySelector('input[type="file"][accept*="image"]');
          if (!fileInput) return Promise.resolve();
          return fetchImageDirect(cleanImageUrl(imageUrl)).then(function (imgResult) {
            if (!imgResult) return;
            var ext = imgResult.mimeType === 'image/png' ? 'png' : 'jpg';
            var file = new File([imgResult.blob], 'sku_preview.' + ext, { type: imgResult.mimeType });
            var dt = new DataTransfer();
            dt.items.add(file);
            fileInput.files = dt.files;
            fileInput.dispatchEvent(new Event('change', { bubbles: true }));
            return delay(300);
          });
        }

        function fillSkuCode() {
          if (!skuCode) return Promise.resolve();
          var inp = td.querySelector('input[data-testid="beast-core-input-htmlInput"]');
          if (inp) {
            inp.focus();
            setInputValue(inp, skuCode);
            inp.dispatchEvent(new Event('blur', { bubbles: true }));
            return delay(150);
          }
          return Promise.resolve();
        }

        var action;
        switch (role) {
          case 'stock': action = fillStock(); break;
          case 'price': action = fillPrice(); break;
          case 'preview': action = fillPreview(); break;
          case 'skuCode': action = fillSkuCode(); break;
          default: action = Promise.resolve();
        }
        return action.then(function () { return processTd(tdIndex + 1); });
      }

      return processTd(0);
    }

    return waitForElement(function () {
      return document.querySelector('.sku-list.list table tbody tr');
    }, 5000, 200).then(function () {
      var skuEntries = skuList.map(function (item, index) {
        var specVals = item.specValues ? Object.values(item.specValues) : [];
        return {
          key: skuEntryKey(specVals, index),
          specVals: specVals,
          item: item
        };
      });
      var filledKeys = {};
      var filledCountRef = { count: 0 };
      var scrollContainer = findSkuScrollContainer();

      function scrollToTop() {
        if (scrollContainer) scrollContainer.scrollTop = 0;
        else window.scrollTo(window.scrollX, 0);
        return delay(700);
      }

      function scrollNextPage() {
        if (scrollContainer) {
          var before = scrollContainer.scrollTop;
          var step = Math.max(240, Math.floor(scrollContainer.clientHeight * 0.8));
          scrollContainer.scrollTop = before + step;
          return delay(800).then(function () {
            return scrollContainer.scrollTop > before + 5;
          });
        }
        var beforeY = window.scrollY;
        window.scrollBy(0, 700);
        return delay(800).then(function () {
          return window.scrollY > beforeY + 5;
        });
      }

      function hasUnfilledSku() {
        for (var i = 0; i < skuEntries.length; i++) {
          if (!filledKeys[skuEntries[i].key]) return true;
        }
        return false;
      }

      function matchSku(rowData) {
        for (var i = 0; i < skuEntries.length; i++) {
          var entry = skuEntries[i];
          if (filledKeys[entry.key]) continue;
          var allMatch = entry.specVals.length
            ? entry.specVals.every(function (v) { return rowData.specTexts.includes(v); })
            : true;
          if (allMatch) return entry;
        }
        return null;
      }

      function fillVisibleRows() {
        var rowSpecMap = buildVisibleRowSpecMap();
        if (!rowSpecMap.length) {
          console.warn('[PDD填充插件] SKU 表格无数据行');
          return Promise.resolve(0);
        }
        var matches = [];
        for (var i = 0; i < rowSpecMap.length; i++) {
          var entry = matchSku(rowSpecMap[i]);
          if (entry) matches.push({ entry: entry, row: rowSpecMap[i].row });
        }
        return matches.reduce(function (promise, match) {
          return promise.then(function () {
            if (filledKeys[match.entry.key]) return Promise.resolve();
            return fillOneVisibleRow(match.entry, match.row, filledCountRef, skuEntries.length).then(function () {
              filledKeys[match.entry.key] = true;
              return delay(300);
            });
          });
        }, Promise.resolve()).then(function () {
          return matches.length;
        });
      }

      function processPages(pageIndex, stagnantPages) {
        if (!hasUnfilledSku()) return Promise.resolve(filledCountRef.count);
        if (pageIndex > skuEntries.length * 3) {
          console.warn('[PDD填充插件] SKU 虚拟表格滚动次数达到上限，停止填充');
          return Promise.resolve(filledCountRef.count);
        }
        var beforeFilled = filledCountRef.count;
        return fillVisibleRows().then(function () {
          var madeProgress = filledCountRef.count > beforeFilled;
          if (!hasUnfilledSku()) return filledCountRef.count;
          return scrollNextPage().then(function (moved) {
            if (!moved) {
              if (!madeProgress || stagnantPages >= 2) {
                var missing = skuEntries.filter(function (s) { return !filledKeys[s.key]; }).map(function (s) { return s.key.replace(/\u001f/g, ' / '); });
                console.warn('[PDD填充插件] SKU 表格已滚到底，仍未填充:', missing);
                return filledCountRef.count;
              }
              return processPages(pageIndex + 1, stagnantPages + 1);
            }
            return processPages(pageIndex + 1, madeProgress ? 0 : stagnantPages + 1);
          });
        });
      }

      return scrollToTop().then(function () {
        return processPages(0, 0);
      });
    });
  }

  function fillSkuExtraFields(data, options) {
    options = options || {};
    var delay = options.delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };
    var setInputValue = options.setInputValue || function () {};

    var marketPrice = data.marketPrice;
    var batchDiscount = data.batchDiscount;
    var productCode = data.productCode;

    function fillMarketPrice() {
      if (!marketPrice) return Promise.resolve();
      var marketArea = document.querySelector('#market_price');
      if (!marketArea) return Promise.resolve();
      var inp = marketArea.querySelector('input[data-testid="beast-core-inputNumber-htmlInput"]');
      if (!inp) return Promise.resolve();
      inp.focus();
      setInputValue(inp, marketPrice);
      inp.dispatchEvent(new Event('blur', { bubbles: true }));
      return delay(200).then(function () {
        console.log('[PDD填充插件] 商品参考价已填充: ' + marketPrice);
      });
    }

    function fillBatchDiscount() {
      if (!batchDiscount) return Promise.resolve();
      var discountArea = document.querySelector('#batch_discount');
      if (!discountArea) return Promise.resolve();
      var inp = discountArea.querySelector('input[data-testid="beast-core-input-htmlInput"]');
      if (!inp) return Promise.resolve();
      inp.focus();
      setInputValue(inp, batchDiscount);
      inp.dispatchEvent(new Event('blur', { bubbles: true }));
      return delay(200).then(function () {
        console.log('[PDD填充插件] 满件折扣已填充: ' + batchDiscount);
      });
    }

    function fillProductCode() {
      if (!productCode) return Promise.resolve();
      var snArea = document.querySelector('#out_goods_sn');
      if (!snArea) return Promise.resolve();
      var inp = snArea.querySelector('input[data-testid="beast-core-input-htmlInput"]');
      if (!inp) return Promise.resolve();
      inp.focus();
      setInputValue(inp, productCode);
      inp.dispatchEvent(new Event('blur', { bubbles: true }));
      return delay(200).then(function () {
        console.log('[PDD填充插件] 商品编码已填充: ' + productCode);
      });
    }

    return fillMarketPrice().then(fillBatchDiscount).then(fillProductCode);
  }

  function clearAllSpecValues(options) {
    options = options || {};
    var delay = options.delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };
    var Toast = options.Toast;

    var container = findSpecArea();
    if (!container) {
      console.warn('[PDD填充插件] 无法找到规格区域');
      return Promise.resolve(false);
    }

    var deleteButtons = container.querySelectorAll('.delete-btn a[data-testid="beast-core-button-link"]');
    if (deleteButtons.length === 0) {
      console.log('[PDD填充插件] 无需清空规格值（已为空）');
      return Promise.resolve(true);
    }

    console.log('[PDD填充插件] 开始清空 ' + deleteButtons.length + ' 个规格值...');
    if (Toast) Toast.show('正在清空规格值...', 'info', 2000);

    function clickOne(index) {
      if (index >= deleteButtons.length) return Promise.resolve();
      var btn = deleteButtons[index];
      btn.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      btn.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
      btn.dispatchEvent(new Event('click', { bubbles: true }));
      return delay(800).then(function () { return clickOne(index + 1); });
    }

    return clickOne(0).then(function () {
      return delay(1000);
    }).then(function () {
      console.log('[PDD填充插件] 规格值清空完成');
      if (Toast) Toast.show('规格值已清空', 'success', 2000);
      return true;
    });
  }

  function fillSkuSection(data, options) {
    options = options || {};
    var delay = options.delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };
    var Toast = options.Toast;
    var fillAllSpecTypesFn = options.fillAllSpecTypes || fillAllSpecTypes;
    var fillSkuBatchFn = options.fillSkuBatch || fillSkuBatch;
    var fillSkuRowsFn = options.fillSkuRows || fillSkuRowsVirtual;
    var fillSkuExtraFieldsFn = options.fillSkuExtraFields || fillSkuExtraFields;
    var completionMessage = options.completionMessage || 'PDDsku表格填充完成';

    if (!data || typeof data !== 'object') {
      if (Toast) Toast.show('填充失败: 规格数据为空或格式不正确', 'error');
      return Promise.resolve();
    }

    console.log('[PDD填充插件] 开始填充规格与库存区域:', data);
    if (Toast) Toast.show('开始填充规格与库存...', 'info', 3000);

    var specTypes = data.specTypes || data.skuAxes || null;
    var skuList = data.skuList || null;
    if (!skuList && data.skus && Array.isArray(data.skus)) {
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
          imageUrl: sku.image || '',
          skuCode: sku.productCode || ''
        };
      });
      console.log('[PDD填充插件] 已将 skus 转换为 skuList:', skuList);
    }

    var batchFill = data.batchFill || null;

    return delay(500).then(function () {
      if (specTypes && Array.isArray(specTypes) && specTypes.length > 0) {
        return fillAllSpecTypesFn(specTypes, options).then(function (totalFilled) {
          var totalValues = specTypes.reduce(function (s, t) {
            return s + (t.values ? t.values.length : 0);
          }, 0);
          if (Toast) Toast.show('规格值填充: ' + totalFilled + '/' + totalValues, 'info', 3000);
          return delay(1500);
        });
      }
    }).then(function () {
      if (skuList && Array.isArray(skuList) && skuList.length > 0) {
        if (Toast) Toast.show('正在逐行填充 SKU 表格...', 'info', 2000);
        return fillSkuRowsFn(skuList, options).then(function (filledRows) {
          if (Toast) Toast.show('SKU 逐行填充: ' + filledRows + '/' + skuList.length, 'info', 3000);
        });
      } else if (batchFill && typeof batchFill === 'object') {
        if (Toast) Toast.show('正在批量设置价格与库存...', 'info', 2000);
        return fillSkuBatchFn(batchFill, options).then(function (batchOk) {
          if (Toast) Toast.show(batchOk ? '批量设置成功' : '批量设置可能未完全生效', batchOk ? 'success' : 'warning', 3000);
        });
      }
    }).then(function () {
      return fillSkuExtraFieldsFn(data, options);
    }).then(function () {
      if (Toast) Toast.show(completionMessage, 'success', 6000);
      console.log('[PDD填充插件] ' + completionMessage);
    });
  }

  return {
    findSpecArea: findSpecArea,
    findSpecRowContainer: findSpecRowContainer,
    clickAddSpecTypeButton: clickAddSpecTypeButton,
    selectSpecType: selectSpecType,
    fillSpecValues: fillSpecValues,
    findExistingSpecContainer: findExistingSpecContainer,
    fillAllSpecTypes: fillAllSpecTypes,
    fillSkuBatch: fillSkuBatch,
    identifyTdRole: identifyTdRole,
    fillSkuRows: fillSkuRows,
    fillSkuRowsVirtual: fillSkuRowsVirtual,
    fillSkuExtraFields: fillSkuExtraFields,
    fillSkuSection: fillSkuSection,
    clearAllSpecValues: clearAllSpecValues
  };
}));
