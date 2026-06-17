// category-handler.js - 类目选择页处理模块
// 处理 /goods/category 页面：逐级选择类目、点击"确认发布该类商品"
// 类目树结构：多列展示，选一级→二级出现→选二级→三级出现→选三级→确认按钮
// 一级类目在 .staple-category-container 折叠分组中（默认 hidden）
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.CategoryHandler = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var LOG_PREFIX = '[PDD类目页]';

  function log() {
    var args = [LOG_PREFIX].concat(Array.prototype.slice.call(arguments));
    console.log.apply(console, args);
  }

  function warn() {
    var args = [LOG_PREFIX].concat(Array.prototype.slice.call(arguments));
    console.warn.apply(console, args);
  }

  function delay(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  function simulateClick(el) {
    el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  }

  function simulateInput(input, value) {
    var nativeSetter;
    try {
      nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    } catch (e) {}
    if (nativeSetter) {
      nativeSetter.call(input, value);
    } else {
      input.value = value;
    }
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    input.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true }));
    input.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
  }

  function isElementVisible(el) {
    if (!el || !document.contains(el)) return false;
    var rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) return false;
    var style = window.getComputedStyle(el);
    return style.display !== 'none' && style.visibility !== 'hidden';
  }

  function waitForElement(finder, maxWait, interval) {
    maxWait = maxWait || 5000;
    interval = interval || 200;
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
    maxWait = maxWait || 3000;
    interval = interval || 150;
    return new Promise(function (resolve) {
      var start = Date.now();
      var tick = function () {
        try { if (checker()) return resolve(true); } catch (e) {}
        if (Date.now() - start <= maxWait) {
          setTimeout(tick, interval);
        } else {
          resolve(false);
        }
      };
      tick();
    });
  }

  function normalizeText(s) {
    return (s || '').replace(/\s+/g, '').replace(/>/g, '').toLowerCase();
  }

  // ====== 方式1：最近使用的分类 ======

  function tryClickRecentCategory(catName) {
    var items = document.querySelectorAll('.always-use-list .choose-category');
    if (items.length === 0) {
      var candidates = [];
      var all = document.querySelectorAll('div, span, button, li, a');
      for (var ai = 0; ai < all.length; ai++) {
        var text = (all[ai].textContent || '').trim();
        if (!text || text.length > 120) continue;
        if (text.includes('>') && text.includes(catName)) {
          candidates.push(all[ai]);
        }
      }
      candidates.sort(function (a, b) {
        return (a.textContent || '').trim().length - (b.textContent || '').trim().length;
      });
      items = candidates;
    }
    if (items.length === 0) return false;

    var target = normalizeText(catName);
    function clickRecentCandidate(el) {
      var current = el;
      for (var depth = 0; current && depth < 5; depth++) {
        if (isElementVisible(current)) {
          simulateClick(current);
        }
        current = current.parentElement;
      }
    }
    log('在最近使用分类中搜索:', catName, '共', items.length, '个条目');

    for (var i = 0; i < items.length; i++) {
      if (!isElementVisible(items[i])) continue;
      var fullText = items[i].textContent.trim();
      var parts = fullText.split('>');
      var lastPart = normalizeText(parts[parts.length - 1]);
      if (lastPart === target) {
        log('最近使用分类精确匹配:', fullText);
        clickRecentCandidate(items[i]);
        return true;
      }
    }

    for (var j = 0; j < items.length; j++) {
      if (!isElementVisible(items[j])) continue;
      var text = normalizeText(items[j].textContent);
      if (text.includes(target)) {
        log('最近使用分类包含匹配:', items[j].textContent.trim());
        clickRecentCandidate(items[j]);
        return true;
      }
    }

    return false;
  }

  // ====== 方式2：逐级浏览类目树（主策略） ======

  /**
   * 在指定列（item-group-container-v2）中查找并点击匹配的类目项
   * 列0是一级类目（在staple分组中），列1+是子级类目
   */
  function findAndClickInColumn(colIdx, catName) {
    var columns = document.querySelectorAll('.item-group-container-v2');
    if (columns.length === 0) {
      columns = document.querySelectorAll('.item-group-container-v3');
    }
    if (colIdx >= columns.length) {
      warn('列索引', colIdx, '超出范围, 共', columns.length, '列');
      return false;
    }

    var column = columns[colIdx];
    var target = normalizeText(catName);

    // 诊断: 列出该列可见类目
    var allNames = column.querySelectorAll('.c-name');
    var visibleNames = [];
    for (var d = 0; d < allNames.length && d < 15; d++) {
      if (isElementVisible(allNames[d])) {
        visibleNames.push(allNames[d].textContent.trim());
      }
    }
    if (visibleNames.length > 0) {
      log('第', colIdx + 1, '列可见类目项:', visibleNames.join(' | '));
    } else {
      log('第', colIdx + 1, '列暂无可见类目项');
    }

    // 精确匹配
    for (var i = 0; i < allNames.length; i++) {
      if (!isElementVisible(allNames[i])) continue;
      var text = normalizeText(allNames[i].textContent);
      if (text === target) {
        var ct = allNames[i].closest('.cate') || allNames[i].closest('.content-cat') || allNames[i];
        log('第', colIdx + 1, '列精确匹配:', allNames[i].textContent.trim());
        simulateClick(ct);
        return true;
      }
    }

    // 包含匹配
    for (var j = 0; j < allNames.length; j++) {
      if (!isElementVisible(allNames[j])) continue;
      var text2 = normalizeText(allNames[j].textContent);
      if (text2.includes(target) || target.includes(text2)) {
        var ct2 = allNames[j].closest('.cate') || allNames[j].closest('.content-cat') || allNames[j];
        log('第', colIdx + 1, '列包含匹配:', allNames[j].textContent.trim());
        simulateClick(ct2);
        return true;
      }
    }

    return false;
  }

  /**
   * 展开包含目标一级类目的分组，并点击该类目
   * 一级类目在 .staple-category-container > ul.level-one-container(hidden) 中
   * 需要先点击 .staple-name-container 展开，再点击匹配的 .c-name
   */
  function expandAndClickLevel1(cat1Name) {
    var groups = document.querySelectorAll('.staple-category-container');
    var target = normalizeText(cat1Name);
    log('查找一级类目:', cat1Name, ', 共', groups.length, '个分组');

    // 遍历每个分组，检查其内容（即使 hidden 也可读 textContent）
    var matchedGroup = null;
    var matchedIdx = -1;
    for (var i = 0; i < groups.length; i++) {
      var list = groups[i].querySelector('.level-one-container');
      if (!list) continue;
      var cNames = list.querySelectorAll('.c-name');
      for (var j = 0; j < cNames.length; j++) {
        if (normalizeText(cNames[j].textContent) === target) {
          matchedGroup = groups[i];
          matchedIdx = j;
          break;
        }
      }
      if (matchedGroup) break;
    }

    // 如果精确匹配失败，尝试包含匹配
    if (!matchedGroup) {
      log('精确匹配一级类目失败, 尝试包含匹配');
      for (var gi = 0; gi < groups.length; gi++) {
        var list2 = groups[gi].querySelector('.level-one-container');
        if (!list2) continue;
        var cNames2 = list2.querySelectorAll('.c-name');
        for (var gj = 0; gj < cNames2.length; gj++) {
          var t = normalizeText(cNames2[gj].textContent);
          if (t.includes(target) || target.includes(t)) {
            matchedGroup = groups[gi];
            matchedIdx = gj;
            break;
          }
        }
        if (matchedGroup) break;
      }
    }

    if (!matchedGroup) {
      warn('所有分组中均未找到一级类目:', cat1Name);
      return Promise.resolve(false);
    }

    var groupNameEl = matchedGroup.querySelector('.staple-name');
    var groupName = groupNameEl ? groupNameEl.textContent.trim() : '(未知)';
    log('在分组"' + groupName + '"中找到一级类目, 索引:', matchedIdx);

    // 展开该分组
    var levelList = matchedGroup.querySelector('.level-one-container');
    if (levelList && levelList.classList.contains('hidden')) {
      var header = matchedGroup.querySelector('.staple-name-container');
      if (header) {
        log('展开分组:', groupName);
        simulateClick(header);
      }
    }

    // 等待展开动画后点击
    return delay(500).then(function () {
      var freshList = matchedGroup.querySelector('.level-one-container');
      if (!freshList) return false;
      var freshNames = freshList.querySelectorAll('.c-name');
      // 先精确再包含
      for (var k = 0; k < freshNames.length; k++) {
        if (normalizeText(freshNames[k].textContent) !== target) continue;
        if (!isElementVisible(freshNames[k])) {
          freshNames[k].scrollIntoView({ block: 'center' });
        }
        var clickEl = freshNames[k].closest('.cate') || freshNames[k].closest('.content-cat') || freshNames[k];
        log('点击一级类目:', freshNames[k].textContent.trim());
        simulateClick(clickEl);
        return true;
      }
      // 包含匹配兜底
      for (var m = 0; m < freshNames.length; m++) {
        var ft = normalizeText(freshNames[m].textContent);
        if (ft.includes(target) || target.includes(ft)) {
          if (!isElementVisible(freshNames[m])) {
            freshNames[m].scrollIntoView({ block: 'center' });
          }
          var clickEl2 = freshNames[m].closest('.cate') || freshNames[m].closest('.content-cat') || freshNames[m];
          log('点击一级类目(包含):', freshNames[m].textContent.trim());
          simulateClick(clickEl2);
          return true;
        }
      }
      warn('展开后仍未找到可点击的一级类目');
      return false;
    });
  }

  /**
   * 逐级浏览选择类目（主策略）
   * 类目是多级结构: cat1Name → cat2Name → cat3Name 依次在不同列中选择
   * 选一级后二级出现在下一个 item-group-container-v2 列中
   */
  function browseAndSelectCategory(catInfo) {
    var levels = [catInfo.cat1Name, catInfo.cat2Name, catInfo.cat3Name, catInfo.cat4Name].filter(Boolean);
    if (levels.length === 0) return Promise.resolve(false);

    log('逐级浏览选择类目:', levels.join(' > '));

    // Step 1: 展开分组并点击一级类目
    return expandAndClickLevel1(levels[0]).then(function (found) {
      if (!found) {
        warn('一级类目选择失败');
        return false;
      }
      log('一级类目选择成功');
      if (levels.length === 1) return true;

      // Step 2: 等待二级列出现，然后选择
      return delay(1000).then(function () {
        return waitForCondition(function () {
          return findAndClickInColumn(1, levels[1]);
        }, 8000, 500);
      }).then(function (found2) {
        if (!found2) {
          warn('二级类目选择失败:', levels[1]);
          return false;
        }
        log('二级类目选择成功');
        if (levels.length === 2) return true;

        // Step 3: 等待三级列出现，然后选择
        return delay(1000).then(function () {
          return waitForCondition(function () {
            return findAndClickInColumn(2, levels[2]);
          }, 8000, 500);
        }).then(function (found3) {
          if (!found3) {
            warn('三级类目选择失败:', levels[2]);
            return false;
          }
          log('三级类目选择成功');
          if (levels.length === 3) return true;

          // Step 4: 四级类目（如果有）
          return delay(1000).then(function () {
            return waitForCondition(function () {
              return findAndClickInColumn(3, levels[3]);
            }, 8000, 500);
          });
        });
      });
    });
  }

  // ====== 方式3：搜索框搜索（备用） ======

  function findCategorySearchInput() {
    var strategies = [
      function () {
        return document.querySelector('input[placeholder*="关键词搜索分类"]') ||
               document.querySelector('input[placeholder*="搜索分类"]');
      },
      function () {
        var container = document.querySelector('.keywords-search');
        if (container) return container.querySelector('input');
        return null;
      },
      function () {
        return document.querySelector('input[refs="searchInput"]');
      }
    ];

    for (var s = 0; s < strategies.length; s++) {
      var result = strategies[s]();
      if (result && isElementVisible(result)) return result;
    }
    return null;
  }

  function findAndClickCategoryOption(catName) {
    var target = normalizeText(catName);
    var cNames = document.querySelectorAll('.c-name');
    for (var i = 0; i < cNames.length; i++) {
      if (!isElementVisible(cNames[i])) continue;
      var text = normalizeText(cNames[i].textContent);
      if (text === target || text.includes(target)) {
        var ct = cNames[i].closest('.cate') || cNames[i].closest('.content-cat') || cNames[i];
        log('搜索结果匹配:', cNames[i].textContent.trim());
        simulateClick(ct);
        return true;
      }
    }
    return false;
  }

  function searchAndSelectCategory(catName) {
    if (!catName) return Promise.resolve(false);
    log('搜索类目:', catName);

    return waitForElement(findCategorySearchInput, 5000, 300).then(function (input) {
      if (!input) {
        warn('未找到类目搜索框');
        return false;
      }

      simulateInput(input, '');
      return delay(300).then(function () {
        simulateClick(input);
        input.focus();
        return delay(300);
      }).then(function () {
        simulateInput(input, catName);
        log('已输入搜索关键词:', catName);
        return delay(1500);
      }).then(function () {
        return waitForCondition(function () {
          return findAndClickCategoryOption(catName);
        }, 6000, 400);
      }).then(function (clicked) {
        if (clicked) {
          log('搜索选择成功:', catName);
          return delay(500).then(function () { return true; });
        }
        warn('搜索未找到:', catName);
        return false;
      });
    });
  }

  // ====== 带回退的类目选择主入口 ======

  /**
   * Phase 1: 最近使用分类 → Phase 2: 逐级浏览类目树 → Phase 3: 搜索框
   */
  function selectCategoryWithFallback(catInfo) {
    var levels = [catInfo.cat1Name, catInfo.cat2Name, catInfo.cat3Name, catInfo.cat4Name].filter(Boolean);
    if (levels.length === 0) {
      warn('没有可用的类目名称');
      return Promise.resolve(false);
    }

    // Phase 1: 最近使用分类（用最后一级名称匹配）
    log('Phase 1: 尝试最近使用分类');
    var lastLevel = levels[levels.length - 1];
    return waitForCondition(function () {
      return tryClickRecentCategory(lastLevel);
    }, 8000, 500).then(function (recentFound) {
      if (recentFound) {
        log('最近使用分类匹配成功:', lastLevel);
        return delay(800).then(function () { return true; });
      }
      log('最近使用分类未匹配');

      // Phase 2: 逐级浏览类目树（展开分组→选一级→选二级→选三级）
      log('Phase 2: 逐级浏览类目树');
      return browseAndSelectCategory(catInfo);
    }).then(function (found) {
      if (found) return true;

      // Phase 3: 搜索框搜索一级类目，然后逐级选子级
      log('Phase 3: 搜索框搜索');
      return searchAndSelectCategory(catInfo.cat1Name).then(function (found1) {
        if (!found1) return false;
        if (levels.length <= 1) return true;
        return delay(1000).then(function () {
          return waitForCondition(function () {
            return findAndClickInColumn(1, levels[1]);
          }, 5000, 400);
        }).then(function (found2) {
          if (!found2 || levels.length <= 2) return !!found2;
          return delay(800).then(function () {
            return waitForCondition(function () {
              return findAndClickInColumn(2, levels[2]);
            }, 5000, 400);
          });
        });
      });
    });
  }

  // ====== 确认按钮 ======

  /**
   * 查找"确认发布该类商品"按钮
   * 实际DOM: <button data-e2e-id="e2e-publish-button" class="BTN_primary_5-178-0">
   *            <span>确认发布该类商品</span>
   *          </button>
   */
  function findConfirmButton() {
    // 优先用 data-e2e-id 精确定位
    var btn = document.querySelector('[data-e2e-id="e2e-publish-button"]');
    if (btn && isElementVisible(btn) && !btn.disabled) return btn;

    // v4 页面的 bottomSubmitBtnId
    var submitBtn = document.getElementById('bottomSubmitBtnId');
    if (submitBtn && isElementVisible(submitBtn) && !submitBtn.disabled) return submitBtn;

    // 按文本兜底
    var buttons = document.querySelectorAll('button[data-testid="beast-core-button"], button');
    for (var i = 0; i < buttons.length; i++) {
      var text = buttons[i].textContent.trim();
      if ((text.includes('确认发布') || text.includes('下一步') || text.includes('填写详情') || text.includes('完善商品')) &&
          isElementVisible(buttons[i]) && !buttons[i].disabled) {
        return buttons[i];
      }
    }
    return null;
  }

  function clickConfirmButton() {
    return waitForElement(findConfirmButton, 10000, 500).then(function (btn) {
      if (!btn) {
        warn('未找到确认/下一步按钮');
        return false;
      }
      log('点击按钮:', btn.textContent.trim());
      simulateClick(btn);
      return delay(500).then(function () { return true; });
    });
  }

  // ====== v4 页面手动选择分类 ======

  /**
   * 点击"手动选择商品分类"按钮，在弹窗中通过搜索/浏览选择类目。
   * 场景A: 无AI推荐 → catePredictList_chooseByUser 中直接显示"选择分类"按钮
   * 场景B: 有AI推荐 → 先点击"查看更多推荐"展开区域，再点"手动选择商品分类"
   */
  function selectPredictedCategory(productData) {
    log('v4: 手动选择分类流程');

    // 查找可直接点击的"选择分类"/"手动选择商品分类"按钮
    function findDirectCategoryButton() {
      // choose_cate_new: 无推荐时的"选择分类"按钮
      var btn = document.querySelector('button[data-tracking-viewid="choose_cate_new"]');
      if (btn && isElementVisible(btn)) return btn;
      // manually_select_product_category: 查看更多后的"手动选择商品分类"
      btn = document.querySelector('button[data-tracking-viewid="manually_select_product_category"]');
      if (btn && isElementVisible(btn)) return btn;
      // 文本匹配兜底
      var buttons = document.querySelectorAll('button');
      for (var i = 0; i < buttons.length; i++) {
        var t = buttons[i].textContent.trim();
        if ((t === '选择分类' || t === '手动选择商品分类' || t.includes('手动选择')) && isElementVisible(buttons[i])) {
          return buttons[i];
        }
      }
      // 容器内按钮兜底
      var chooseByUser = document.querySelector('[class*="catePredictList_chooseByUser"]');
      if (chooseByUser) {
        var innerBtn = chooseByUser.querySelector('button');
        if (innerBtn && isElementVisible(innerBtn)) return innerBtn;
      }
      return null;
    }

    // 查找"查看更多推荐"按钮/链接（AI预测场景）
    function findViewMoreButton() {
      // 精确匹配 data-tracking-viewid
      var tracked = document.querySelector('[data-tracking-viewid="view_more_recommendations"]');
      if (tracked && isElementVisible(tracked)) return tracked;
      tracked = document.querySelector('[data-tracking-viewid*="view_more"]');
      if (tracked && isElementVisible(tracked)) return tracked;
      // 按钮文本匹配
      var btns = document.querySelectorAll('button');
      for (var i = 0; i < btns.length; i++) {
        var t = btns[i].textContent.trim();
        if ((t === '查看更多推荐' || t.includes('更多推荐') || t === '查看更多') && isElementVisible(btns[i])) {
          return btns[i];
        }
      }
      return null;
    }

    // Step 1: 优先检查"查看更多推荐"按钮（AI预测场景需先展开）
    var viewMoreBtn = findViewMoreButton();
    var directBtn;
    var chain;

    if (viewMoreBtn) {
      // 存在"查看更多推荐"按钮 → 先展开，再找"手动选择分类"
      log('点击"查看更多推荐":', viewMoreBtn.textContent.trim());
      simulateClick(viewMoreBtn);
      chain = delay(1500).then(function () {
        return waitForElement(findDirectCategoryButton, 8000, 500);
      }).then(function (btn) {
        if (!btn) {
          warn('展开后仍未找到手动选择分类按钮');
          return false;
        }
        log('点击手动选择分类按钮:', btn.textContent.trim());
        simulateClick(btn);
        return delay(1000);
      });
    } else {
      directBtn = findDirectCategoryButton();
      if (directBtn) {
        log('直接找到分类选择按钮:', directBtn.textContent.trim());
        simulateClick(directBtn);
        chain = delay(1000);
      } else {
        // 等待按钮出现（页面可能还在加载）
        log('等待分类按钮出现...');
        chain = waitForElement(function () {
          return findViewMoreButton() || findDirectCategoryButton();
        }, 15000, 500).then(function (btn) {
          if (!btn) {
            warn('超时未找到分类选择按钮');
            return false;
          }
          // 判断找到的是哪个按钮
          var vmBtn = findViewMoreButton();
          if (vmBtn) {
            log('等到"查看更多推荐"按钮, 点击');
            simulateClick(vmBtn);
            return delay(1500).then(function () {
              return waitForElement(findDirectCategoryButton, 8000, 500);
            }).then(function (manualBtn) {
              if (!manualBtn) return false;
              log('点击手动选择分类按钮:', manualBtn.textContent.trim());
              simulateClick(manualBtn);
              return delay(1000);
            });
          } else {
            log('等到分类选择按钮:', btn.textContent.trim());
            simulateClick(btn);
            return delay(1000);
          }
        });
      }
    }

    return chain.then(function (result) {
      if (result === false) return false;

      // Step 2: 等待分类选择弹窗出现
      return waitForElement(function () {
        var modal = document.querySelector('[data-testid="beast-core-modal-body"]');
        if (modal && isElementVisible(modal)) return modal;
        var selectMain = document.querySelector('[class*="cate-select-modal_selectMainV3"]');
        if (selectMain && isElementVisible(selectMain)) return selectMain;
        // v2 样式弹窗
        var selectMainV2 = document.querySelector('.select-main-v2');
        if (selectMainV2 && isElementVisible(selectMainV2)) return selectMainV2;
        return null;
      }, 8000, 300);
    }).then(function (modal) {
      if (!modal) {
        warn('手动选择分类弹窗未出现');
        return false;
      }
      log('分类选择弹窗已打开');

      // Step 3: 在弹窗中根据商品数据的类目信息选择正确分类
      // 不使用最近使用/推荐分类，直接搜索或逐级浏览类目树
      return selectCategoryInModal(modal, productData);
    });
  }

  /**
   * 在分类选择弹窗中，根据商品数据的类目信息选择正确的分类
   * 策略: 优先搜索最后一级类目名称 → 逐级浏览类目树 → 搜索一级类目再逐级选
   * 不使用"最近使用分类"，因为可能匹配到错误的类目
   */
  function selectCategoryInModal(modal, productData) {
    var levels = [productData.cat1Name, productData.cat2Name, productData.cat3Name, productData.cat4Name].filter(Boolean);
    if (levels.length === 0) {
      warn('商品数据中没有类目信息');
      return Promise.resolve(false);
    }
    log('弹窗内选择类目:', levels.join(' > '));

    // 在弹窗内查找搜索框
    function findModalSearchInput() {
      // 优先在 modal 容器内查找
      var input = modal.querySelector('input[placeholder*="关键词搜索分类"]') ||
                  modal.querySelector('input[placeholder*="搜索分类"]') ||
                  modal.querySelector('input[refs="searchInput"]');
      if (input && isElementVisible(input)) return input;
      // 兜底：在 .select-main-v2 / .keywords-search 中查找
      var container = modal.querySelector('.keywords-search') ||
                      document.querySelector('.select-main-v2 .keywords-search');
      if (container) {
        input = container.querySelector('input');
        if (input && isElementVisible(input)) return input;
      }
      // 最后使用全局查找（弹窗可能挂在 body 下）
      return findCategorySearchInput();
    }

    // 在弹窗内逐级浏览找到可见的 .c-name 并点击
    function findAndClickInModalColumn(colIdx, catName) {
      // 弹窗内的列容器（支持 v2 和 v3）
      var modalParent = modal.closest('[data-testid="beast-core-modal-body"]') ||
                         modal.closest('[class*="cate-select-modal_selectMainV3"]') ||
                         modal.closest('.select-main-v2') || modal;
      // 优先查找 v3 容器，再回退到 v2（与非弹窗 findAndClickInColumn 保持一致）
      var columns = modalParent.querySelectorAll('.item-group-container-v3');
      if (columns.length === 0) {
        columns = modalParent.querySelectorAll('.item-group-container-v2');
      }
      if (columns.length === 0) {
        columns = document.querySelectorAll('.item-group-container-v3');
      }
      if (columns.length === 0) {
        columns = document.querySelectorAll('.item-group-container-v2');
      }
      if (colIdx >= columns.length) {
        warn('弹窗列索引', colIdx, '超出范围, 共', columns.length, '列');
        return false;
      }
      var column = columns[colIdx];
      var target = normalizeText(catName);

      // 诊断: 列出该列可见类目
      var allNames = column.querySelectorAll('.c-name');
      var visibleNames = [];
      for (var d = 0; d < allNames.length && d < 15; d++) {
        if (isElementVisible(allNames[d])) {
          visibleNames.push(allNames[d].textContent.trim());
        }
      }
      if (visibleNames.length > 0) {
        log('弹窗第', colIdx + 1, '列可见类目项:', visibleNames.join(' | '));
      } else {
        log('弹窗第', colIdx + 1, '列暂无可见类目项');
      }

      // 精确匹配
      for (var i = 0; i < allNames.length; i++) {
        if (!isElementVisible(allNames[i])) continue;
        var text = normalizeText(allNames[i].textContent);
        if (text === target) {
          var ct = allNames[i].closest('.cate') || allNames[i].closest('.content-cat') || allNames[i];
          log('弹窗第', colIdx + 1, '列精确匹配:', allNames[i].textContent.trim());
          simulateClick(ct);
          return true;
        }
      }
      // 包含匹配
      for (var j = 0; j < allNames.length; j++) {
        if (!isElementVisible(allNames[j])) continue;
        var text2 = normalizeText(allNames[j].textContent);
        if (text2.includes(target) || target.includes(text2)) {
          var ct2 = allNames[j].closest('.cate') || allNames[j].closest('.content-cat') || allNames[j];
          log('弹窗第', colIdx + 1, '列包含匹配:', allNames[j].textContent.trim());
          simulateClick(ct2);
          return true;
        }
      }
      return false;
    }

    // Phase 1: 搜索最后一级类目名（最精确）
    var lastLevel = levels[levels.length - 1];
    log('弹窗 Phase 1: 搜索最后一级类目:', lastLevel);

    return waitForElement(findModalSearchInput, 5000, 300).then(function (searchInput) {
      if (!searchInput) {
        log('弹窗内未找到搜索框，跳转到逐级浏览');
        return 'no-search';
      }

      // 清空搜索框
      simulateInput(searchInput, '');
      return delay(300).then(function () {
        simulateClick(searchInput);
        searchInput.focus();
        return delay(300);
      }).then(function () {
        // 搜索最后一级类目名
        simulateInput(searchInput, lastLevel);
        log('弹窗搜索:', lastLevel);
        return delay(1500);
      }).then(function () {
        // 在搜索结果中查找完整路径匹配的类目
        return waitForCondition(function () {
          var cNames = document.querySelectorAll('.c-name');
          var target = normalizeText(lastLevel);
          // 优先找完整路径匹配（所有层级都匹配）
          for (var i = 0; i < cNames.length; i++) {
            if (!isElementVisible(cNames[i])) continue;
            // 检查该类目项的完整路径文本
            var row = cNames[i].closest('.cate') || cNames[i].closest('.content-cat') || cNames[i].closest('li') || cNames[i];
            var fullText = normalizeText(row.textContent);
            var allMatch = true;
            for (var li = 0; li < levels.length; li++) {
              if (!fullText.includes(normalizeText(levels[li]))) {
                allMatch = false;
                break;
              }
            }
            if (allMatch) {
              log('弹窗搜索：完整路径匹配:', row.textContent.trim());
              simulateClick(row);
              return true;
            }
          }
          // 如果没有完整路径匹配，匹配最后一级类目名
          for (var j = 0; j < cNames.length; j++) {
            if (!isElementVisible(cNames[j])) continue;
            var text = normalizeText(cNames[j].textContent);
            if (text === target || text.includes(target)) {
              var ct = cNames[j].closest('.cate') || cNames[j].closest('.content-cat') || cNames[j];
              log('弹窗搜索：名称匹配:', cNames[j].textContent.trim());
              simulateClick(ct);
              return true;
            }
          }
          return false;
        }, 6000, 400);
      }).then(function (found) {
        if (found) {
          log('弹窗搜索类目成功');
          return delay(500).then(function () { return true; });
        }
        // 搜索失败，清空搜索框并尝试逐级浏览
        log('弹窗搜索类目失败，清空搜索框尝试逐级浏览');
        simulateInput(searchInput, '');
        return delay(500).then(function () { return 'no-search'; });
      });
    }).then(function (result) {
      if (result === true) return true;

      // Phase 2: 逐级浏览类目树（在弹窗内）
      log('弹窗 Phase 2: 逐级浏览类目树');
      return expandAndClickLevel1(levels[0]).then(function (found1) {
        if (!found1) {
          warn('弹窗一级类目选择失败:', levels[0]);
          return false;
        }
        log('弹窗一级类目选择成功');
        if (levels.length === 1) return true;

        return delay(1000).then(function () {
          return waitForCondition(function () {
            return findAndClickInModalColumn(1, levels[1]);
          }, 8000, 500);
        }).then(function (found2) {
          if (!found2) {
            warn('弹窗二级类目选择失败:', levels[1]);
            return false;
          }
          log('弹窗二级类目选择成功');
          if (levels.length === 2) return true;

          return delay(1000).then(function () {
            return waitForCondition(function () {
              return findAndClickInModalColumn(2, levels[2]);
            }, 8000, 500);
          }).then(function (found3) {
            if (!found3) {
              warn('弹窗三级类目选择失败:', levels[2]);
              return false;
            }
            log('弹窗三级类目选择成功');
            if (levels.length === 3) return true;

            return delay(1000).then(function () {
              return waitForCondition(function () {
                return findAndClickInModalColumn(3, levels[3]);
              }, 8000, 500);
            });
          });
        });
      });
    }).then(function (categorySelected) {
      if (!categorySelected) {
        warn('弹窗内类目选择失败');
        return false;
      }

      // 点击弹窗内的"确认"按钮
      log('类目选择成功，点击弹窗确认按钮');
      return delay(500).then(function () {
        // 优先用 data-tracking-click-viewid 精确定位
        var confirmBtn = document.querySelector('button[data-tracking-click-viewid="cate_confirm"]');
        if (!confirmBtn || !isElementVisible(confirmBtn)) {
          // 兜底：在弹窗 footer 中查找"确认"按钮
          var footerBtns = document.querySelectorAll('[class*="MDL_footer"] button');
          for (var i = 0; i < footerBtns.length; i++) {
            var t = footerBtns[i].textContent.trim();
            if (t === '确认' && isElementVisible(footerBtns[i]) && !footerBtns[i].disabled) {
              confirmBtn = footerBtns[i];
              break;
            }
          }
        }
        if (confirmBtn && isElementVisible(confirmBtn)) {
          log('点击弹窗确认按钮:', confirmBtn.textContent.trim());
          simulateClick(confirmBtn);
          return delay(1000).then(function () { return true; });
        }
        warn('未找到弹窗确认按钮');
        return true; // 类目已选中，即使没找到确认按钮也算成功
      });
    });
  }

  // ====== 页面变体检测 ======

  /**
   * 检测当前类目页是哪种变体：
   * - v2: 传统类目树选择（item-group-container-v2, staple-category-container）
   * - v3: AI智能识别类目（ImageSearchPanel, 上传主轮播图后将为您智能识别类目）
   * - v4: 带图片+标题的表单（goodsTitle, goodsCarousel, goodsNameId）
   * - unknown: 无法识别
   */
  function detectPageVariant() {
    var bodyText = document.body && (document.body.innerText || document.body.textContent || '');
    if (bodyText && bodyText.includes('商品主图') && bodyText.includes('商品标题') &&
        (bodyText.includes('下一步') || bodyText.includes('完善商品信息'))) {
      log('检测到 v4 发布前信息页');
      return 'v4';
    }
    // v2: 传统类目树
    if (document.querySelector('.item-group-container-v2') || document.querySelector('.staple-category-container')) {
      log('检测到 v2 类目树页面');
      return 'v2';
    }
    // v3: AI分类识别（ImageSearchPanel + 第2步 "选择商品分类"）
    if (document.querySelector('[class*="ImageSearchPanel"]') || document.querySelector('.cate-container-v3')) {
      log('检测到 v3 AI分类页面');
      return 'v3';
    }
    // v4: 带标题+图片的表单（goodsNameId / goodsCarousel）
    if (document.querySelector('#goodsNameId') || document.querySelector('[class*="cateContainerV4"]') ||
        document.querySelector('#goodsCarousel')) {
      log('检测到 v4 表单页面');
      return 'v4';
    }
    // v4 变体: AI预测分类列表（catePredictList / selectedCateId）
    if (document.querySelector('#selectedCateId') ||
        document.querySelector('[class*="catePredictList"]') ||
        document.querySelector('[data-tracking-viewid="view_more_recommendations"]')) {
      log('检测到 v4 AI预测分类页面');
      return 'v4';
    }
    log('未识别的页面变体, 尝试按通用逻辑处理');
    return 'unknown';
  }

  // ====== v3/v4 页面标题填充 ======

  /**
   * 在 v4 类目页填充商品标题
   * 标题在 #goodsNameId 容器中, input[placeholder*="商品标题"]
   */
  function fillTitleOnCategoryPage(title) {
    if (!title) return Promise.resolve(false);

    return waitForElement(function () {
      // 直接找标题输入框
      var input = document.querySelector('#goodsNameId input[type="text"]') ||
                  document.querySelector('#goods_name input[type="text"]') ||
                  document.querySelector('input[placeholder*="商品标题"]') ||
                  document.querySelector('input[placeholder*="商品描述"]');
      if (input && isElementVisible(input)) return input;
      return null;
    }, 10000, 300).then(function (input) {
      if (!input) {
        log('v3/v4 页面未找到标题输入框, 可能该变体无标题字段');
        return false;
      }
      log('填充标题:', title);
      simulateClick(input);
      input.focus();
      simulateInput(input, title);
      return delay(300).then(function () {
        // 必须 blur + 点击页面空白区域，触发 React 重新渲染分类区域
        input.dispatchEvent(new Event('blur', { bubbles: true }));
        input.blur();
        // 点击页面空白区域确保 input 彻底失焦
        var blankArea = document.querySelector('[class*="catePanel"]') ||
                        document.querySelector('[class*="category_v4"]') ||
                        document.querySelector('main') ||
                        document.body;
        simulateClick(blankArea);
        log('标题填充完成，已 blur 输入框并点击空白区域');
        return delay(2000); // 等待页面渲染分类区域
      }).then(function () { return true; });
    });
  }

  function getPrefillPageState() {
    var body = document.body && (document.body.innerText || document.body.textContent || '');
    var titleInput = document.querySelector('#goodsNameId input[type="text"]') ||
                     document.querySelector('#goods_name input[type="text"]') ||
                     document.querySelector('input[placeholder*="商品标题"]') ||
                     document.querySelector('input[placeholder*="商品描述"]');
    var uploadMatch = body && body.match(/上传图片\s*\((\d+)\s*\/\s*\d+\)/);
    var imageCount = uploadMatch ? Number(uploadMatch[1]) : 0;
    if (!imageCount) {
      var carousel = document.querySelector('#goodsCarousel') ||
                     document.querySelector('#goodsCarouselId') ||
                     document.body;
      var imgs = carousel ? carousel.querySelectorAll('img, div[style*="background-image"]') : [];
      for (var i = 0; i < imgs.length; i++) {
        var rect = imgs[i].getBoundingClientRect();
        if (rect.width >= 24 && rect.height >= 24) imageCount++;
      }
    }
    return {
      isPrefill: !!(body && body.includes('商品主图') && body.includes('商品标题') &&
        (body.includes('下一步') || body.includes('完善商品信息'))),
      imageCount: imageCount,
      title: titleInput ? (titleInput.value || '').trim() : ''
    };
  }

  function waitForPrefillRequiredFields(expectedTitle, minImages) {
    minImages = minImages || 1;
    return waitForCondition(function () {
      var state = getPrefillPageState();
      var hasImages = state.imageCount >= minImages;
      var hasTitle = !!state.title;
      if (expectedTitle) hasTitle = state.title === expectedTitle || state.title.indexOf(expectedTitle) >= 0;
      return hasImages && hasTitle;
    }, 15000, 500).then(function (ok) {
      if (!ok) {
        var state = getPrefillPageState();
        warn('发布前信息页必填项未完成:', state);
      }
      return ok;
    });
  }

  // ====== 完整类目页填充流程 ======

  function fillCategoryPage(productData, deps) {
    log('开始类目页填充流程');
    log('类目信息:', productData.cat1Name, '>', productData.cat2Name, '>', productData.cat3Name, '>', productData.cat4Name);
    var results = { category: false, confirm: false };

    if (detectPageVariant() === 'v4') {
      log('传统类目流程检测到发布前信息页，跳过类目树选择，直接填标题并点下一步');
      return fillTitleOnCategoryPage(productData.title || '').then(function () {
        return waitForPrefillRequiredFields(productData.title || '', 1);
      }).then(function (ready) {
        if (!ready) return false;
        return delay(500).then(function () {
          return clickConfirmButton();
        });
      }).then(function (ok) {
        return {
          success: !!ok,
          results: { category: true, confirm: !!ok, skippedCategoryTree: true },
          error: ok ? undefined : '下一步按钮点击失败'
        };
      });
    }

    return selectCategoryWithFallback({
      cat1Name: productData.cat1Name,
      cat2Name: productData.cat2Name,
      cat3Name: productData.cat3Name,
      cat4Name: productData.cat4Name
    }).then(function (ok) {
      results.category = ok;
      log('类目选择结果:', ok);
      return delay(1500);
    }).then(function () {
      return clickConfirmButton().then(function (ok) {
        results.confirm = ok;
        log('点击确认结果:', ok);
        return delay(500);
      });
    }).then(function () {
      var allOk = results.category && results.confirm;
      log('类目页填充完成, 结果:', results);
      return {
        success: allOk,
        results: results,
        error: allOk ? undefined : '类目选择或确认失败'
      };
    }).catch(function (err) {
      warn('类目页填充异常:', err);
      return { success: false, error: err.message || String(err) };
    });
  }

  return {
    searchAndSelectCategory: searchAndSelectCategory,
    selectCategoryWithFallback: selectCategoryWithFallback,
    browseAndSelectCategory: browseAndSelectCategory,
    tryClickRecentCategory: tryClickRecentCategory,
    clickNextStep: clickConfirmButton,
    selectPredictedCategory: selectPredictedCategory,
    fillCategoryPage: fillCategoryPage,
    findCategorySearchInput: findCategorySearchInput,
    findNextStepButton: findConfirmButton,
    detectPageVariant: detectPageVariant,
    fillTitleOnCategoryPage: fillTitleOnCategoryPage,
    getPrefillPageState: getPrefillPageState,
    waitForPrefillRequiredFields: waitForPrefillRequiredFields
  };
}));
