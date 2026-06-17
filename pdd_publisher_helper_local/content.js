// content.js — PDD商品发布助手 Content Script
// 支持两种模式：1) background.js 轮询驱动（主模式） 2) RPA postMessage（兼容模式）
(function () {
  'use strict';

  var Utils, InputHandler, SelectHandler, ImageHandler, SkuHandler, MainModule, CategoryHandler, ImageFission;
  var Toast, Logger;

  // 当前页面类型
  var PAGE_TYPE = detectPageType();
  var LAST_URL = window.location.href;

  function detectPageType() {
    var url = window.location.href;
    var bodyText = document.body && (document.body.innerText || document.body.textContent || '');
    if (url.includes('/goods/goods_add/index')) return 'detail';
    if (url.includes('/goods/category')) return 'category';
    if (url.includes('/publish/new') || url.includes('/publish/edit')) return 'detail';
    if (bodyText && bodyText.includes('商品主图') && bodyText.includes('商品标题') &&
        (bodyText.includes('下一步') || bodyText.includes('完善商品信息'))) return 'category';
    if (bodyText && (bodyText.includes('选择商品分类') || bodyText.includes('商品分类')) &&
        (bodyText.includes('下一步') || bodyText.includes('确认'))) return 'category';
    if (bodyText && (bodyText.includes('商品视频') || bodyText.includes('商品讲解视频') ||
        bodyText.includes('保存草稿') || bodyText.includes('商品详情'))) return 'detail';
    if (url.includes('/ssp/') || url.includes('/ad/') || url.includes('/promotion/')) return 'promotion';
    if (url.includes('/goods/goods_list')) return 'goods_list';
    return 'unknown';
  }

  function refreshPageType() {
    var url = window.location.href;
    var nextType = detectPageType();
    if (url !== LAST_URL || nextType !== PAGE_TYPE) {
      LAST_URL = url;
      PAGE_TYPE = nextType;
      if (Logger) Logger.info('检测到页面地址变化，页面类型更新为:', PAGE_TYPE, url);
      reportWorkbenchProgress('page_changed', '检测到页面跳转，当前页面类型：' + PAGE_TYPE, { url: url });
    }
    return PAGE_TYPE;
  }

  function initModules() {
    Utils = window.Utils;
    InputHandler = window.InputHandler;
    SelectHandler = window.SelectHandler;
    ImageHandler = window.ImageHandler;
    SkuHandler = window.SkuHandler;
    MainModule = window.MainModule;
    CategoryHandler = window.CategoryHandler;
    ImageFission = window.ImageFission || {
      processCarouselImages: function (productData) {
        return Promise.resolve(productData.carouselImages);
      }
    };

    Logger = new Utils.Logger('[PDD填充插件]');
    Toast = MainModule.Toast;
  }

  function reportWorkbenchProgress(stage, message, detail) {
    try {
      fetch('http://127.0.0.1:8765/api/plugin-progress', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          stage: stage,
          message: message,
          detail: detail || null,
          page_type: PAGE_TYPE,
          url: window.location.href,
          ok: stage !== 'error'
        })
      }).catch(function () {});
    } catch (_) {}
  }

  function getInputOptions() {
    return {
      delay: Utils.delay,
      simulateClick: Utils.simulateClick,
      setInputValue: InputHandler.setInputValue,
      typeLikeHuman: InputHandler.syncTypeLikeHuman
    };
  }

  function getSelectOptions() {
    return {
      delay: Utils.delay,
      simulateClick: Utils.simulateClick,
      setInputValue: InputHandler.setInputValue,
      findPopup: SelectHandler.findPopup,
      findAndClickOption: SelectHandler.findAndClickOption,
      isSelectValueSet: SelectHandler.isSelectValueSet,
      isMultiSelectValueSet: SelectHandler.isMultiSelectValueSet,
      waitForElement: Utils.waitForElement,
      waitForCondition: Utils.waitForCondition,
      closeDropdown: SelectHandler.closeDropdown
    };
  }

  function getSkuOptions() {
    return {
      delay: Utils.delay,
      setInputValue: InputHandler.setInputValue,
      simulateClick: Utils.simulateClick,
      waitForElement: Utils.waitForElement,
      Toast: Toast,
      typeLikeHuman: InputHandler.syncTypeLikeHuman,
      fillSelect: SelectHandler.fillSelect,
      fetchImageDirect: ImageHandler.fetchImageDirect,
      cleanImageUrl: ImageHandler.cleanImageUrl
    };
  }

  // ====== 详情页填充功能（沿用原有逻辑） ======

  function fillAttributes(attrArray) {
    if (!Array.isArray(attrArray) || attrArray.length === 0) {
      Toast.show('收到的属性数据为空或格式不正确', 'error');
      return Promise.resolve(false);
    }
    Logger.info('开始填充，属性数量:', attrArray.length);

    var pending = attrArray.filter(function (a) { return a.name && a.value; });
    var skippedEmpty = attrArray.length - pending.length;
    var skipCount = skippedEmpty;
    var successCount = 0;
    var failedNames = [];
    var MAX_ROUNDS = 5;
    var round = 0;

    Toast.show('开始填充 ' + attrArray.length + ' 个属性...', 'info', 3000);

    return new Promise(function (resolve) {
      function runRound() {
        if (pending.length === 0 || round >= MAX_ROUNDS) {
          finalize();
          return;
        }

        round++;
        Logger.info('=== 第 ' + round + ' 轮扫描，待填充: ' + pending.length + ' 个 ===');

        var filledThisRound = 0;
        var stillPending = [];
        var chain = Promise.resolve();

        for (var pi = 0; pi < pending.length; pi++) {
          var attr = pending[pi];
          (function (a, idx) {
            chain = chain.then(function () {
              var propertyMap = MainModule.buildPropertyMap();
              if (filledThisRound === 0 && idx === 0) {
                Logger.info('当前页面属性:', Array.from(propertyMap.keys()));
              }

              var total = attrArray.length;
              var done = successCount + 1;
              Toast.show('正在填充 (' + done + '/' + total + '): ' + a.name, 'info', 2000);

              return fillOneAttribute(a, propertyMap).then(function (result) {
                if (result === 'success') {
                  successCount++;
                  filledThisRound++;
                  return Utils.delay(300);
                } else if (result === 'not-found') {
                  stillPending.push(a);
                } else if (result === 'failed') {
                  Logger.warn(a.name + ' 填充失败，将在下一轮重试');
                  stillPending.push(a);
                } else {
                  skipCount++;
                }
                return Utils.delay(200);
              });
            });
          })(attr, pi);
        }

        return chain.then(function () {
          pending.length = 0;
          pending.push.apply(pending, stillPending);

          if (filledThisRound === 0 && pending.length > 0) {
            Logger.info('本轮无新进展，等待页面动态渲染...');
            return Utils.delay(1500).then(function () {
              var retryMap = MainModule.buildPropertyMap();
              var finalPending = [];
              var retryChain = Promise.resolve();

              for (var ri = 0; ri < pending.length; ri++) {
                var rAttr = pending[ri];
                (function (ra) {
                  retryChain = retryChain.then(function () {
                    return fillOneAttribute(ra, retryMap).then(function (result) {
                      if (result === 'success') {
                        successCount++;
                        return Utils.delay(600);
                      } else if (result === 'not-found') {
                        finalPending.push(ra);
                      } else {
                        skipCount++;
                      }
                      return Utils.delay(400);
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
        var summaryType = failedNames.length === 0 ? 'success' : 'warning';
        Toast.show('PDD属性填充完成', summaryType, 6000);
        Toast.show('成功: ' + successCount + ', 跳过: ' + skipCount, 'info', 6000);

        if (failedNames.length > 0) {
          Toast.show('未匹配属性: ' + failedNames.join(', '), 'error', 8000);
        }

        Logger.info('PDD属性填充完成, 成功:', successCount, '跳过:', skipCount);
        resolve(failedNames.length === 0);
      }

      Utils.delay(500).then(function () {
        runRound();
      });
    });
  }

  function fillOneAttribute(attr, propertyMap) {
    var name = attr.name;
    var value = attr.value;
    if (!name || !value) return Promise.resolve('skip');

    var match = MainModule.findPropertyEl(name, propertyMap);
    if (!match) return Promise.resolve('not-found');

    var control = SelectHandler.detectControlType(match.el);
    Logger.info(name + ' → 类型: ' + control.type + ', 值: ' + value);

    var selectOpts = getSelectOptions();

    if (control.type === 'select') {
      return SelectHandler.fillSelect(control, value, selectOpts).then(function (filled) {
        return filled ? 'success' : 'failed';
      });
    } else if (control.type === 'multi-select') {
      return SelectHandler.fillMultiSelect(control, value, selectOpts).then(function (filled) {
        return filled ? 'success' : 'failed';
      });
    } else if (control.type === 'input') {
      return InputHandler.fillTextInput(control, value, Utils.delay, Utils.simulateClick).then(function (filled) {
        return filled ? 'success' : 'failed';
      });
    } else if (control.type === 'datepicker') {
      Logger.warn('日期选择器暂不支持自动填充: ' + name);
      return Promise.resolve('skip');
    } else {
      Logger.warn('未知控件类型: ' + name);
      return Promise.resolve('skip');
    }
  }

  function fillTitle(title) {
    MainModule.fillTitle(title);
    return Promise.resolve(true);
  }

  function uploadImages(imageItems, options) {
    var opts = {
      Toast: Toast,
      delay: Utils.delay
    };
    if (options) {
      for (var key in options) {
        if (options.hasOwnProperty(key)) opts[key] = options[key];
      }
    }
    return ImageHandler.uploadImages(imageItems, opts);
  }

  function uploadDetailImages(imageDataArray) {
    return ImageHandler.uploadDetailImages(imageDataArray, {
      Toast: Toast,
      delay: Utils.delay
    });
  }

  function uploadVideo(videoItem, labels) {
    return ImageHandler.uploadVideo(videoItem, labels, {
      Toast: Toast,
      delay: Utils.delay
    });
  }

  function uploadSkuImages(imageDataArray) {
    return ImageHandler.uploadSkuImages(imageDataArray, {
      Toast: Toast,
      delay: Utils.delay
    });
  }

  function fillSkuSection(data, options) {
    var skuOpts = getSkuOptions();
    if (options) {
      for (var key in options) {
        if (options.hasOwnProperty(key)) {
          skuOpts[key] = options[key];
        }
      }
    }
    return SkuHandler.fillSkuSection(data, skuOpts);
  }

  function collectMainImageItems(productData) {
    var items = [];
    var seen = {};

    function add(url, meta) {
      url = String(url || '').trim();
      if (!url || seen[url]) return;
      seen[url] = true;
      var item = { url: url };
      if (meta && meta.size) item.size = meta.size;
      if (meta && meta.name) item.name = meta.name;
      items.push(item);
    }

    function addFromObject(obj) {
      if (!obj || Array.isArray(obj)) return;
      for (var key in obj) {
        if (obj.hasOwnProperty(key)) add(obj[key]);
      }
    }

    function addFromArray(arr) {
      if (!Array.isArray(arr)) return;
      arr.forEach(function (item) {
        if (typeof item === 'string') {
          add(item);
        } else if (item && typeof item === 'object') {
          add(item.url, {
            size: item.size || ((item.width && item.height) ? (item.width + 'x' + item.height) : ''),
            name: item.name || item.filename || ''
          });
        }
      });
    }

    addFromObject(productData.carouselImages);
    addFromArray(productData.carouselImages);
    addFromObject(productData.mainImages);
    addFromArray(productData.main_images);
    addFromArray(productData.mainImages);
    return items;
  }

  function uploadPrefillMainImages(productData) {
    var items = collectMainImageItems(productData);
    if (!items.length) {
      Logger.warn('发布前信息页没有可用主图数据');
      return Promise.resolve(false);
    }
    Logger.info('发布前信息页补上传主图，数量:', items.length);
    return uploadImages(items, {
      fileInputFinder: ImageHandler.findPrefillMainImageFileInput,
      areaFinder: ImageHandler.findPrefillMainImageArea
    }).then(function (ok) {
      return Utils.delay(2500).then(function () { return !!ok; });
    });
  }

  function ensurePrefillRequiredFields(productData) {
    var state = CategoryHandler.getPrefillPageState();
    if (!state.isPrefill) return Promise.resolve(true);
    var chain = Promise.resolve();

    if (state.imageCount < 1) {
      reportWorkbenchProgress('category_prefill_upload_images', '发布前信息页：正在补上传商品主图');
      chain = chain.then(function () {
        return uploadPrefillMainImages(productData);
      });
    }

    chain = chain.then(function () {
      var latest = CategoryHandler.getPrefillPageState();
      if (productData.title && latest.title !== productData.title) {
        reportWorkbenchProgress('category_prefill_fill_title', '发布前信息页：正在补填写商品标题');
        return CategoryHandler.fillTitleOnCategoryPage(productData.title);
      }
      return true;
    });

    return chain.then(function () {
      return CategoryHandler.waitForPrefillRequiredFields(productData.title || '', 1);
    });
  }

  // ====== 类目页完整填充流程 ======

  function handleCategoryFill(productData, fissionConfig) {
    Logger.info('===== 类目页填充流程开始 =====');
    reportWorkbenchProgress('category_start', '已收到任务，正在发布新商品页选择类目');

    var variant = CategoryHandler.detectPageVariant();
    Logger.info('检测到类目页变体:', variant);
    reportWorkbenchProgress('category_detected', '已识别类目页，准备选择明装小拉手', { variant: variant });

    if (variant === 'v3' || variant === 'v4') {
      // v3/v4: 先上传图片、填标题，再点下一步
      Toast.show('开始填充（' + variant + ' 图片+标题+下一步）...', 'info', 3000);

      var chain = Promise.resolve();

      // Step 0: 裂变轮播图（如果需要）
      chain = chain.then(function () {
        reportWorkbenchProgress('category_upload_main_images', '类目页：正在上传主图用于识别类目');
        return ImageFission.processCarouselImages(productData, fissionConfig).then(function (newImages) {
          if (newImages !== productData.carouselImages) {
            Logger.info('v3/v4 Step 0: 轮播图裂变完成，已替换图片URL');
            Toast.show('AI裂变主图完成', 'success', 3000);
          }
          productData.carouselImages = newImages;
        });
      });

      // Step 1: 上传轮播图（在v3上可触发AI分类）
      chain = chain.then(function () {
        var items = collectMainImageItems(productData);
        if (items.length > 0) {
          Logger.info('v3/v4 Step 1: 上传轮播图');
          return uploadImages(items, {
            fileInputFinder: ImageHandler.findPrefillMainImageFileInput,
            areaFinder: ImageHandler.findPrefillMainImageArea
          }).then(function () {
            return Utils.delay(3000); // 等待图片上传和AI识别
          });
        }
        return Promise.resolve();
      });

      // Step 2: 填充标题（v4 有标题输入框，v3 可能没有）
      chain = chain.then(function () {
        reportWorkbenchProgress('category_fill_title', '类目页：正在填写标题并等待系统推荐类目');
        if (productData.title) {
          Logger.info('v3/v4 Step 2: 填充标题');
          return CategoryHandler.fillTitleOnCategoryPage(productData.title).then(function () {
            // fillTitleOnCategoryPage 已包含 blur + 2s 等待
            // 额外等待确保分类预测区域渲染完成
            return Utils.delay(2000);
          });
        }
        return Promise.resolve();
      });

      // Step 3: 校验发布前信息页必填项
      chain = chain.then(function () {
        Logger.info('v3/v4 Step 3: 校验主图和标题已填');
        reportWorkbenchProgress('category_prefill_check', '类目页：正在确认主图和标题已填写');
        return ensurePrefillRequiredFields(productData).then(function (ready) {
          if (!ready) {
            throw new Error('发布前信息页主图或标题未填写完成');
          }
          return Utils.delay(500);
        });
      });

      // Step 4: 等待 AI 预测分类并选择
      chain = chain.then(function () {
        Logger.info('v3/v4 Step 4: 手动选择分类');
        reportWorkbenchProgress('category_select', '类目页：正在选择最近使用分类/小拉手类目');
        return CategoryHandler.selectPredictedCategory(productData).then(function (ok) {
          if (!ok) {
            Logger.warn('手动分类选择失败，仍尝试点击下一步');
          }
          return Utils.delay(500);
        });
      });

      // Step 5: 点击"下一步"
      chain = chain.then(function () {
        Logger.info('v3/v4 Step 5: 点击下一步按钮');
        reportWorkbenchProgress('category_next', '类目页：正在点击确认，进入商品编辑页');
        return CategoryHandler.clickNextStep();
      });

      return chain.then(function (ok) {
        Logger.info('v3/v4 类目页填充结果:', ok);
        chrome.runtime.sendMessage({
          type: 'CATEGORY_FILL_COMPLETE',
          success: !!ok,
          error: ok ? undefined : '下一步按钮点击失败'
        });
        if (ok) {
          reportWorkbenchProgress('category_done', '类目页完成，等待进入商品编辑页继续填充');
          Toast.show('类目页填充完成，正在跳转...', 'success', 3000);
        } else {
          reportWorkbenchProgress('error', '类目页下一步失败，请检查当前页面');
          Toast.show('类目页填充失败', 'error', 5000);
        }
      }).catch(function (err) {
        Logger.error('v3/v4 类目页填充异常:', err);
        chrome.runtime.sendMessage({
          type: 'CATEGORY_FILL_COMPLETE',
          success: false,
          error: err.message || String(err)
        });
        reportWorkbenchProgress('error', '类目页执行异常：' + (err.message || String(err)));
      });
    } else {
      // v2: 传统类目树选择流程
      Toast.show('开始类目页自动填充（类目选择）...', 'info', 3000);

      return CategoryHandler.fillCategoryPage(productData, {}).then(function (result) {
        Logger.info('类目页填充结果:', result);
        reportWorkbenchProgress(result.success ? 'category_done' : 'error', result.success ? '类目页完成，等待进入商品编辑页继续填充' : '类目页填充失败：' + (result.error || '未知原因'));
        chrome.runtime.sendMessage({
          type: 'CATEGORY_FILL_COMPLETE',
          success: result.success,
          error: result.error
        });
        if (result.success) {
          Toast.show('类目页填充完成，正在跳转...', 'success', 3000);
        } else {
          Toast.show('类目页填充失败: ' + (result.error || ''), 'error', 5000);
        }
      });
    }
  }

  // ====== 详情页完整填充流程 ======

  function handleDetailFill(productData, fissionConfig) {
    Logger.info('===== 详情页填充流程开始 =====');
    reportWorkbenchProgress('detail_wait', '已进入商品编辑页，正在等待页面加载完成');
    Toast.show('等待详情页加载完成...', 'info', 5000);

    // 等待详情页关键元素加载完毕
    return waitForDetailPageReady().then(function () {
      Logger.info('详情页已加载就绪，开始填充');
      reportWorkbenchProgress('detail_start', '商品编辑页已加载，开始自动填充');
      Toast.show('开始详情页自动填充...', 'info', 3000);
      return executeDetailFill(productData);
    }).catch(function (err) {
      Logger.warn('详情页等待超时，仍尝试填充:', err);
      reportWorkbenchProgress('detail_start', '页面加载较慢，已超时但继续尝试填充');
      Toast.show('页面未完全加载，尝试填充...', 'warning', 3000);
      return executeDetailFill(productData);
    });
  }

  /**
   * 等待详情页关键DOM元素加载完毕
   * 检测: 图片上传区域 / 标题输入框 / 底部操作按钮
   */
  function waitForDetailPageReady() {
    var startTime = Date.now();
    var maxWait = 60000; // 最多等60秒（慢网络）
    var checkInterval = 800;

    return new Promise(function (resolve, reject) {
      function check() {
        var elapsed = Date.now() - startTime;

        // ====== 1. 检测页面级加载遮罩层（Beast Core Spin 组件）======
        // 加载中: Spn_container_ 带有 Spn_spinning_ 类，显示 Spn_spinningMask_ 白色半透明遮罩
        var hasLoadingOverlay = false;

        // Beast Core Spin: container 处于 spinning 状态
        var spinningContainers = document.querySelectorAll('[class*="Spn_spinning"]');
        for (var si = 0; si < spinningContainers.length; si++) {
          // 排除 header 搜索区域的小 Spin（只关注主内容区的大遮罩）
          var spinEl = spinningContainers[si];
          if (spinEl.closest && spinEl.closest('.mms-header_search_new_dropdown')) continue;
          if (spinEl.offsetParent !== null || spinEl.offsetWidth > 0) {
            hasLoadingOverlay = true;
            break;
          }
        }

        // 全屏/大区域 Spin block 模式
        if (!hasLoadingOverlay) {
          var blockSpins = document.querySelectorAll('[class*="Spn_spin"][class*="Spn_block"]');
          for (var bi = 0; bi < blockSpins.length; bi++) {
            if (blockSpins[bi].offsetParent !== null) {
              hasLoadingOverlay = true;
              break;
            }
          }
        }

        // 通用 loading 遮罩层检测（class 含 loading-mask / loadingMask / loading-overlay）
        if (!hasLoadingOverlay) {
          var genericMasks = document.querySelectorAll(
            '[class*="loading-mask"], [class*="loadingMask"], [class*="loading-overlay"], [class*="loadingOverlay"], [class*="page-loading"], [class*="pageLoading"]'
          );
          for (var gi = 0; gi < genericMasks.length; gi++) {
            if (genericMasks[gi].offsetParent !== null && genericMasks[gi].offsetHeight > 100) {
              hasLoadingOverlay = true;
              break;
            }
          }
        }

        // ====== 2. 检查关键元素是否存在 ======
        var hasImageArea = !!(
          document.querySelector('#picture') ||
          document.querySelector('#basic\\.carousel_gallery') ||
          document.querySelector('[id="goodsCarousel"]') ||
          document.querySelector('input[type="file"][accept*="image"]')
        );

        var hasTitleInput = !!(
          document.querySelector('#goods_name input') ||
          document.querySelector('#goodsNameId input') ||
          document.querySelector('textarea[data-testid*="input"]')
        );

        var hasFooterAction = !!(function () {
          var btns = document.querySelectorAll('button, [role="button"]');
          for (var i = 0; i < btns.length; i++) {
            var t = (btns[i].textContent || '').replace(/\s+/g, '').trim();
            if ((t === '保存草稿' || t === '取消') && btns[i].offsetParent !== null) {
              return true;
            }
          }
          return false;
        })();

        Logger.info('页面就绪检测 (' + Math.round(elapsed / 1000) + 's): 遮罩=' + hasLoadingOverlay + ', 图片区=' + hasImageArea + ', 标题=' + hasTitleInput + ', 底部操作=' + hasFooterAction);

        // ====== 3. 判断是否就绪 ======
        // 必须: 无加载遮罩 + 至少有图片区域和标题输入框
        if (!hasLoadingOverlay && hasImageArea && hasTitleInput) {
          // 遮罩刚消失，等待额外时间确保 React 数据绑定/渲染全部完成
          Logger.info('遮罩已消失且关键元素就绪，等待数据渲染稳定...');
          setTimeout(resolve, 2000);
          return;
        }

        if (elapsed >= maxWait) {
          reject(new Error('详情页加载超时'));
          return;
        }

        setTimeout(check, checkInterval);
      }
      check();
    });
  }

  function executeDetailFill(productData) {
    var steps = [];
    var stepResults = {};

    // Step 1: 本地版只填独立生成/选用后的标题
    steps.push(function () {
      if (productData.title) {
        Logger.info('Step 1: 填充商品标题');
        reportWorkbenchProgress('detail_title', '详情页：正在填写商品标题');
        return fillTitle(productData.title).then(function () {
          stepResults.title = true;
          reportWorkbenchProgress('detail_title_done', '详情页：商品标题已填写');
          return Utils.delay(800);
        });
      }
      Logger.info('Step 1: 未找到商品标题，跳过标题填充');
      return Promise.resolve();
    });

    // Step 2: 上传轮播图（如果已上传则跳过）
    steps.push(function () {
      if (productData.carouselImages) {
        reportWorkbenchProgress('detail_main_images', '详情页：正在检查/上传主图');
        // 检测是否已有上传的轮播图（类目页可能已上传）
        var pictureArea = document.querySelector('#picture') ||
                          document.querySelector('#basic\\.carousel_gallery') ||
                          document.querySelector('[id="goodsCarouselId"]') ||
                          document.querySelector('[id="goodsCarousel"]') ||
                          document.querySelector('[data-tracking-viewid="el_upload_wheel_chart"]');
        if (pictureArea) {
          var existingImgs = pictureArea.querySelectorAll('[class*="MaterialModalButton_v2_imgContainer"], [class*="MaterialModalButton_v2_imageBox"]');
          if (existingImgs.length === 0) {
            // 兜底检查 background-image
            var bgDivs = pictureArea.querySelectorAll('div[style*="background-image"]');
            for (var di = 0; di < bgDivs.length; di++) {
              var bgStyle = bgDivs[di].style.backgroundImage || '';
              if (bgStyle.indexOf('pddpic.com') !== -1 || bgStyle.indexOf('pinduoduo.com') !== -1) {
                existingImgs = [bgDivs[di]]; // 存在至少一张
                break;
              }
            }
          }
          if (existingImgs.length > 0) {
            Logger.info('Step 2: 已检测到 ' + existingImgs.length + ' 张已上传轮播图，跳过上传');
            reportWorkbenchProgress('detail_main_images_done', '详情页：已检测到主图，跳过重复上传', { count: existingImgs.length });
            return Promise.resolve();
          }
        }

        Logger.info('Step 2: 上传轮播图');
        var items = [];
        var imgs = productData.carouselImages;
        for (var k in imgs) {
          if (imgs.hasOwnProperty(k) && imgs[k]) {
            items.push({ url: imgs[k] });
          }
        }
        if (items.length > 0) {
          return uploadImages(items).then(function () {
            stepResults.images = true;
            reportWorkbenchProgress('detail_main_images_done', '详情页：主图上传完成', { count: items.length });
            return Utils.delay(1000);
          });
        }
      }
      return Promise.resolve();
    });

    // Step 3: Fill the common listing attributes from the local workbench.
    steps.push(function () {
      var videoTasks = [];
      if (productData.productVideo) {
        videoTasks.push(function () {
          reportWorkbenchProgress('detail_product_video', '详情页：正在上传商品视频');
          return uploadVideo(productData.productVideo, ['商品视频']).then(function (ok) {
            stepResults.productVideo = !!ok;
            reportWorkbenchProgress(ok ? 'detail_product_video_done' : 'detail_product_video_skipped', ok ? '详情页：商品视频已上传' : '详情页：商品视频未上传，请检查入口');
          });
        });
      }
      if (productData.explainVideo) {
        videoTasks.push(function () {
          reportWorkbenchProgress('detail_explain_video', '详情页：正在上传商品讲解视频');
          return uploadVideo(productData.explainVideo, ['商品讲解视频', '讲解视频']).then(function (ok) {
            stepResults.explainVideo = !!ok;
            reportWorkbenchProgress(ok ? 'detail_explain_video_done' : 'detail_explain_video_skipped', ok ? '详情页：商品讲解视频已上传' : '详情页：商品讲解视频未上传，请检查入口');
          });
        });
      }
      return videoTasks.reduce(function (chain, task) {
        return chain.then(task).then(function () { return Utils.delay(800); });
      }, Promise.resolve());
    });

    // Step 3: Fill the common listing attributes from the local workbench.
    steps.push(function () {
      var attrs = Array.isArray(productData.attributes) ? productData.attributes.filter(function (attr) {
        return attr && attr.name && attr.value;
      }) : [];

      if (attrs.length > 0) {
        Logger.info('Step 3: fill common attributes', attrs);
        reportWorkbenchProgress('detail_attributes', '详情页：正在填写商品属性');
        return fillAttributes(attrs).then(function (ok) {
          stepResults.attributes = !!ok;
          reportWorkbenchProgress(ok ? 'detail_attributes_done' : 'detail_attributes_partial', ok ? '详情页：商品属性已填写' : '详情页：商品属性部分未选中，请检查页面');
          return Utils.delay(800);
        });
      }

      Logger.info('Step 3: no attributes found, skip attribute fill');
      return Promise.resolve();
    });

    // Step 4: 填充SKU规格。先创建规格和价格，避免详情图上传等待阻塞SKU
    steps.push(function () {
      if (productData.skuAxes || productData.skus) {
        Logger.info('Step 4: 填充SKU');
        reportWorkbenchProgress('detail_sku', '详情页：正在创建规格、上传尺寸图、填写价格库存');
        var skuData = {};
        if (productData.skuAxes) skuData.skuAxes = productData.skuAxes;
        if (productData.marketPrice) skuData.marketPrice = productData.marketPrice;
        if (productData.batchDiscount) skuData.batchDiscount = productData.batchDiscount;
        if (productData.productCode) skuData.productCode = productData.productCode;
        if (productData.skus) {
          skuData.skuList = productData.skus.map(function (sku) {
            var specValues = {};
            if (sku.specs) {
              for (var si = 0; si < sku.specs.length; si++) {
                specValues[sku.specs[si].key] = sku.specs[si].value;
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

        // SKU 图片由 fillSkuRows 的 fillPreview 逐行上传（需要 SKU 表格先渲染）
        // 不再提前批量上传，因为此时 SKU 表格尚未生成

        return fillSkuSection(skuData).then(function () {
          stepResults.sku = true;
          reportWorkbenchProgress('detail_sku_done', '详情页：规格、尺寸图、价格库存已处理');
          return Utils.delay(1000);
        });
      }
      return Promise.resolve();
    });

    // Step 5: 上传详情图
    steps.push(function () {
      if (productData.detailImages && productData.detailImages.length > 0) {
        Logger.info('Step 5: 上传详情图');
        reportWorkbenchProgress('detail_images', '详情页：正在上传详情页图片', { count: productData.detailImages.length });
        var items = productData.detailImages.map(function (url) { return { url: url }; });
        return uploadDetailImages(items).then(function () {
          stepResults.detailImages = true;
          reportWorkbenchProgress('detail_images_done', '详情页：详情图片上传完成', { count: items.length });
          return Utils.delay(1000);
        });
      }
      return Promise.resolve();
    });

    // Step 6: 自动保存草稿，不提交上架
    steps.push(function () {
      Logger.info('Step 6: 检查并保存草稿');
      return saveDraftAfterValidation(productData, stepResults);
    });

    // Step 7: 本地安全版不提交上架
    steps.push(function () {
      Logger.info('Step 7: 已保存草稿或停在待检查状态，不会提交上架');
      return Promise.resolve();
    });

    // 串行执行所有步骤
    var chain = Promise.resolve();
    for (var i = 0; i < steps.length; i++) {
      (function (step) {
        chain = chain.then(step);
      })(steps[i]);
    }

    return chain.then(function () {
      Logger.info('详情页填充流程完成:', stepResults);
      reportWorkbenchProgress('done', stepResults.draftSaved ? '自动填充完成，草稿已保存' : '自动填充完成，但草稿未自动保存，请人工检查', stepResults);
      Toast.show('详情页填充完成', 'success', 5000);
      chrome.runtime.sendMessage({
        type: 'DETAIL_FILL_COMPLETE',
        success: true,
        results: stepResults
      });
    }).catch(function (err) {
      Logger.error('详情页填充异常:', err);
      reportWorkbenchProgress('error', '详情页填充异常：' + (err.message || String(err)));
      Toast.show('详情页填充异常: ' + err.message, 'error', 5000);
      chrome.runtime.sendMessage({
        type: 'DETAIL_FILL_COMPLETE',
        success: false,
        error: err.message
      });
    });
  }

  function validateBeforeSaveDraft(productData, stepResults) {
    var missing = [];
    if (productData.title && !stepResults.title) missing.push('标题');
    if (productData.carouselImages && Object.keys(productData.carouselImages).length > 0 && !stepResults.images) {
      var pictureArea = document.querySelector('#picture') ||
                        document.querySelector('#basic\\.carousel_gallery') ||
                        document.querySelector('[id="goodsCarouselId"]') ||
                        document.querySelector('[id="goodsCarousel"]');
      var existing = pictureArea ? pictureArea.querySelectorAll('[class*="imgContainer"], [class*="imageBox"], div[style*="background-image"]').length : 0;
      if (existing === 0) missing.push('主图');
    }
    if ((productData.skuAxes || productData.skus) && !stepResults.sku) missing.push('规格和价格');
    if (productData.detailImages && productData.detailImages.length > 0 && !stepResults.detailImages) missing.push('详情图');
    return missing;
  }

  function findSaveDraftButton() {
    var buttons = document.querySelectorAll('button, [role="button"]');
    for (var i = 0; i < buttons.length; i++) {
      var btn = buttons[i];
      var text = (btn.textContent || '').replace(/\s+/g, '').trim();
      if (text === '保存草稿' && !btn.disabled && btn.offsetParent !== null) {
        return btn;
      }
    }
    return null;
  }

  function clickSaveDraftButton() {
    var btn = findSaveDraftButton();
    if (!btn) return false;
    btn.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    btn.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    btn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return true;
  }

  function saveDraftAfterValidation(productData, stepResults) {
    var missing = validateBeforeSaveDraft(productData, stepResults);
    if (missing.length > 0) {
      var msg = '自动填充未完全通过检查，不保存草稿：' + missing.join('、');
      Logger.warn(msg);
      stepResults.draftSaved = false;
      stepResults.draftSkippedReason = msg;
      reportWorkbenchProgress('draft_skipped', msg, stepResults);
      Toast.show(msg, 'warning', 8000);
      return Promise.resolve(false);
    }

    reportWorkbenchProgress('draft_saving', '正在保存草稿，不会提交上架', stepResults);
    Toast.show('正在保存草稿...', 'info', 5000);
    if (!clickSaveDraftButton()) {
      var notFound = '未找到“保存草稿”按钮，已停在页面等待人工检查';
      Logger.warn(notFound);
      stepResults.draftSaved = false;
      stepResults.draftSkippedReason = notFound;
      reportWorkbenchProgress('draft_skipped', notFound, stepResults);
      Toast.show(notFound, 'warning', 8000);
      return Promise.resolve(false);
    }

    stepResults.draftSaved = true;
    return Utils.delay(3000).then(function () {
      reportWorkbenchProgress('draft_saved', '草稿已点击保存，请在草稿箱核对', stepResults);
      Toast.show('草稿已保存，请到草稿箱核对', 'success', 6000);
      return true;
    });
  }

  // ====== chrome.runtime.onMessage 监听（主模式：background.js 驱动） ======

  function setupBackgroundListener() {
    chrome.runtime.onMessage.addListener(function (message, sender, sendResponse) {
      if (message.type === 'START_CATEGORY_FILL') {
        Logger.info('收到类目页填充指令');
        handleCategoryFill(message.data, message.fissionConfig);
        sendResponse({ received: true, pageType: PAGE_TYPE });
        return false;
      }

      if (message.type === 'START_DETAIL_FILL') {
        Logger.info('收到详情页填充指令');
        handleDetailFill(message.data, message.fissionConfig);
        sendResponse({ received: true, pageType: PAGE_TYPE });
        return false;
      }

      if (message.type === 'GET_PAGE_STATUS') {
        sendResponse({
          pageType: PAGE_TYPE,
          url: window.location.href,
          ready: !!(Utils && MainModule)
        });
        return false;
      }

    });
  }

  // ====== 本地工作台插件模式：只处理商品发布，不打开推广页 ======
  function setupLocalWorkbenchPolling() {
    if (window.__pdd_local_workbench_polling) return;
    window.__pdd_local_workbench_polling = true;

    var API_BASE = 'http://127.0.0.1:8765';
    var PENDING_KEY = 'pdd_local_pending_product';
    var DETAIL_RUNNING_KEY = 'pdd_local_detail_running_product';
    var DETAIL_DONE_KEY = 'pdd_local_detail_done_product';
    var busy = false;
    var detailFallbackStarted = false;
    var materialBusy = false;
    var lastMaterialRequestId = null;

    function isForegroundPage() {
      return document.visibilityState === 'visible' && !document.hidden;
    }

    function productRunKey(productData) {
      var skuCount = productData && Array.isArray(productData.skus) ? productData.skus.length : 0;
      return [
        productData && productData.title || '',
        productData && productData.productCode || '',
        skuCount,
        window.location.pathname
      ].join('|');
    }

    function fetchJson(url, options) {
      return fetch(url, options || {}).then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      });
    }

    function claimTask(item) {
      return fetchJson(API_BASE + '/api/curd/product_json_store/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: item.id,
          query_count: Math.max(0, Number(item.query_count || 1) - 1)
        })
      });
    }

    function parseMaterialFile(item) {
      var name = String((item && item.name) || '');
      var extension = String((item && item.extension) || '');
      var extra = (item && item.extra_info) || {};
      return {
        id: Number(item.id || 0),
        filename: extension ? name + '.' + extension : name,
        name: name,
        extension: extension,
        url: String(item.url || ''),
        width: extra.width,
        height: extra.height,
        size: extra.size
      };
    }

    function materialExtension(file) {
      var ext = String((file && file.extension) || '').toLowerCase().replace(/^\./, '');
      if (ext) return ext;
      var filename = String((file && file.filename) || (file && file.name) || '').toLowerCase();
      var match = filename.match(/\.([a-z0-9]+)$/);
      return match ? match[1] : '';
    }

    function listMaterialDir(dirId, pageSize) {
      return fetch('https://mms.pinduoduo.com/garner/mms/file/dir_list', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          if_query_dir: true,
          order_by: 'create_time desc',
          dir_id: dirId || 0,
          page: 1,
          page_size: pageSize || 100,
          file_param: { file_type_desc: '' },
          dir_param: {}
        })
      }).then(function (res) {
        if (!res.ok) throw new Error('图片空间接口 HTTP ' + res.status);
        return res.json();
      }).then(function (json) {
        if (!json || !json.success) {
          throw new Error('图片空间目录读取失败: ' + ((json && (json.error_msg || json.msg)) || '未知错误'));
        }
        var result = json.result || {};
        var folders = (result.dir_list || []).map(function (item) {
          return {
            id: Number(item.id || 0),
            name: String(item.name || ''),
            parent_dir_id: Number(item.parent_dir_id || 0)
          };
        });
        var files = (result.file_list || []).map(parseMaterialFile);
        return { folders: folders, files: files };
      });
    }

    function findMaterialFolder(parentDirId, name) {
      return listMaterialDir(parentDirId, 100).then(function (result) {
        for (var i = 0; i < result.folders.length; i++) {
          if (result.folders[i].name === name) return result.folders[i];
        }
        var candidates = result.folders.slice(0, 20).map(function (folder) { return folder.name; }).join(', ');
        throw new Error('图片空间找不到文件夹 ' + name + '；当前候选: ' + candidates);
      });
    }

    function resolveMaterialPath(path) {
      var parts = String(path || '').split(/[\\/]+/).filter(Boolean);
      if (!parts.length) return Promise.reject(new Error('图片空间路径不能为空'));
      var current = null;
      var parentId = 0;
      var chain = Promise.resolve();
      parts.forEach(function (part) {
        chain = chain.then(function () {
          return findMaterialFolder(parentId, part).then(function (folder) {
            current = folder;
            parentId = folder.id;
          });
        });
      });
      return chain.then(function () { return current; });
    }

    function readMaterialPath(path) {
      return resolveMaterialPath(path).then(function (folder) {
        return listMaterialDir(folder.id, 100).then(function (rootListing) {
          var children = {};
          var childChain = Promise.resolve();
          rootListing.folders.forEach(function (child) {
            childChain = childChain.then(function () {
              return listMaterialDir(child.id, 200).then(function (childListing) {
                children[child.name] = childListing.files.filter(function (file) {
                  return ['jpg', 'jpeg', 'png', 'webp', 'mp4', 'mov', 'webm', 'm4v'].indexOf(materialExtension(file)) >= 0;
                });
              });
            });
          });
          return childChain.then(function () {
            return {
              path: path,
              dir_id: folder.id,
              child_folders: rootListing.folders,
              files: rootListing.files,
              children: children
            };
          });
        });
      });
    }

    function postMaterialResponse(payload) {
      return fetchJson(API_BASE + '/api/material-read/response', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
    }

    function pollMaterialRequest() {
      refreshPageType();
      if (materialBusy || !isForegroundPage() || !window.location.href.includes('mms.pinduoduo.com')) return;
      fetchJson(API_BASE + '/api/material-read/request')
        .then(function (json) {
          var request = json && json.data ? json.data : {};
          if (!request.id || request.status !== 'pending') return null;
          if (String(request.id) === String(lastMaterialRequestId)) return null;
          return request;
        })
        .then(function (request) {
          if (!request) return;
          materialBusy = true;
          lastMaterialRequestId = request.id;
          Toast.show('插件模式：读取图片空间 ' + request.path, 'info', 3000);
          return readMaterialPath(request.path)
            .then(function (data) {
              return postMaterialResponse({ id: request.id, data: data });
            })
            .catch(function (err) {
              return postMaterialResponse({ id: request.id, error: err.message || String(err) });
            })
            .finally(function () {
              materialBusy = false;
            });
        })
        .catch(function (err) {
          Logger.warn('图片空间请求轮询失败:', err.message);
        });
    }

    function runProductData(productData) {
      refreshPageType();
      if (!productData) return Promise.resolve(false);
      if (PAGE_TYPE === 'category') {
        reportWorkbenchProgress('task_received', '当前发布页已收到上架任务，准备选择类目');
        Toast.show('插件模式：开始选择类目', 'info', 3000);
        sessionStorage.setItem(PENDING_KEY, JSON.stringify(productData));
        return Promise.resolve(handleCategoryFill(productData, {}));
      }
      if (PAGE_TYPE === 'detail') {
        var runKey = productRunKey(productData);
        if (sessionStorage.getItem(DETAIL_RUNNING_KEY) === runKey) {
          Logger.warn('当前商品详情页正在自动填充，跳过重复触发');
          return Promise.resolve(false);
        }
        if (sessionStorage.getItem(DETAIL_DONE_KEY) === runKey) {
          Logger.warn('当前商品详情页已经自动填充过，跳过重复触发，避免清空规格');
          reportWorkbenchProgress('done', '当前商品编辑页已填充过，已阻止重复执行，避免清空规格');
          return Promise.resolve(false);
        }
        detailFallbackStarted = true;
        sessionStorage.setItem(DETAIL_RUNNING_KEY, runKey);
        reportWorkbenchProgress('task_received', '当前商品编辑页已收到上架任务，准备填充详情');
        Toast.show('插件模式：开始填商品详情', 'info', 3000);
        return Promise.resolve(handleDetailFill(productData, {})).then(function (result) {
          sessionStorage.setItem(DETAIL_DONE_KEY, runKey);
          return result;
        }).finally(function () {
          sessionStorage.removeItem(DETAIL_RUNNING_KEY);
          sessionStorage.removeItem(PENDING_KEY);
        });
      }
      return Promise.resolve(false);
    }

    function consumePendingOnDetailPage() {
      refreshPageType();
      if (PAGE_TYPE !== 'detail' || busy || !isForegroundPage()) return;
      var raw = sessionStorage.getItem(PENDING_KEY);
      if (!raw) {
        if (detailFallbackStarted) return;
        detailFallbackStarted = true;
        busy = true;
        fetchJson(API_BASE + '/api/current-product-json')
          .then(function (json) {
            var productData = json && json.data ? json.data : null;
          if (!productData) {
            Logger.warn('详情页兜底读取不到当前上架包');
            return false;
          }
          reportWorkbenchProgress('task_recovered', '详情页没有缓存任务，已从工作台兜底读取上架包');
          Toast.show('插件模式：详情页兜底读取上架包并开始填充', 'info', 3000);
          return runProductData(productData);
          })
          .catch(function (err) {
            Logger.warn('详情页兜底读取失败:', err.message);
          })
          .finally(function () {
            busy = false;
          });
        return;
      }
      try {
        busy = true;
        runProductData(JSON.parse(raw)).finally(function () {
          busy = false;
        });
      } catch (err) {
        busy = false;
        Logger.warn('读取本地待填商品失败:', err.message);
      }
    }

    function pollOnce() {
      refreshPageType();
      if (busy || !isForegroundPage() || (PAGE_TYPE !== 'category' && PAGE_TYPE !== 'detail')) return;
      consumePendingOnDetailPage();
      if (busy) return;
      if (sessionStorage.getItem(PENDING_KEY)) {
        if (PAGE_TYPE === 'detail') return;
        Logger.warn('分类页发现旧的待填商品缓存，已清理后继续读取新任务');
        sessionStorage.removeItem(PENDING_KEY);
      }

      fetchJson(API_BASE + '/api/curd/product_json_store/list?page=1&size=1')
        .then(function (json) {
          var list = json && json.data && Array.isArray(json.data.list) ? json.data.list : [];
          if (!list.length) return null;
          return list[0];
        })
        .then(function (item) {
          if (!item || busy) return;
          busy = true;
          var productData = JSON.parse(item.json_data || '{}');
          reportWorkbenchProgress('task_claiming', '前台发布页发现待上架任务，正在接收任务');
          return claimTask(item)
            .then(function () { return runProductData(productData); })
            .finally(function () { busy = false; });
        })
        .catch(function (err) {
          Logger.warn('本地工作台轮询失败:', err.message);
        });
    }

    consumePendingOnDetailPage();
    setInterval(pollMaterialRequest, 2000);
    setInterval(pollOnce, 3000);
    setInterval(function () {
      refreshPageType();
      consumePendingOnDetailPage();
    }, 1000);
    pollMaterialRequest();
    pollOnce();
    Logger.info('本地工作台插件模式已启用，只处理商品发布页任务');
  }

  // ====== 注入 inject.js（兼容RPA模式） ======
  var script = document.createElement('script');
  script.src = chrome.runtime.getURL('inject.js');
  script.onload = function () { this.remove(); };
  (document.head || document.documentElement).appendChild(script);

  // ====== 等待模块加载后初始化 ======
  function waitForModules(callback) {
    var retries = 0;
    var maxRetries = 50;

    function check() {
      var coreReady = window.Utils && window.InputHandler && window.SelectHandler &&
          window.ImageHandler && window.SkuHandler && window.MainModule;
      // 类目页需要 CategoryHandler
      var categoryReady = PAGE_TYPE !== 'category' || window.CategoryHandler;

      if (coreReady && categoryReady) {
        initModules();
        callback();
      } else if (retries < maxRetries) {
        retries++;
        setTimeout(check, 100);
      } else {
        console.error('[PDD填充插件] 模块加载超时');
        // 即使超时也尝试初始化已加载的模块
        if (coreReady) {
          initModules();
          callback();
        }
      }
    }
    check();
  }

  waitForModules(function () {
    Logger.info('模块加载完成, 页面类型:', PAGE_TYPE);

    // 设置 background.js 消息监听（主模式）
    setupBackgroundListener();

    // 设置 RPA 事件监听（兼容模式）
    MainModule.setupEventListeners({
      fillAttributes: fillAttributes,
      fillTitle: fillTitle,
      uploadImages: function (items) { uploadImages(items); },
      uploadDetailImages: function (items) { uploadDetailImages(items); },
      uploadSkuImages: function (items) { uploadSkuImages(items); },
      fillSku: fillSkuSection
    });

    Toast.show('PDD商品发布助手已就绪 [' + PAGE_TYPE + ']', 'success', 3000);
    Logger.info('content.js 已加载, 页面类型:', PAGE_TYPE, ', 等待指令...');
    setupLocalWorkbenchPolling();

  });
})();
