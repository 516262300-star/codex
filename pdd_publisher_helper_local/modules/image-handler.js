// image-handler.js - 图片上传模块
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.ImageHandler = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  function fetchImageDirect(url) {
    var isPddpicDomain = false;
    try {
      isPddpicDomain = new URL(url).hostname.includes('pddpic.com');
    } catch (e) {}

    function tryFetch() {
      return fetch(url).then(function (response) {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.blob();
      }).then(function (blob) {
        var mimeType = blob.type || 'image/jpeg';
        return { blob: blob, mimeType: mimeType, size: blob.size };
      });
    }

    function tryViaBackground() {
      return new Promise(function (resolve) {
        chrome.runtime.sendMessage({ type: 'FETCH_IMAGE', url: url }, function (response) {
          if (chrome.runtime.lastError || !response || !response.success) {
            resolve(null);
            return;
          }
          var arr = response.dataUrl.split(',');
          var mime = response.mimeType || ((arr[0] && arr[0].match(/:(.*?);/)) ? arr[0].match(/:(.*?);/)[1] : 'image/jpeg');
          var bstr = atob(arr[1]);
          var u8arr = new Uint8Array(bstr.length);
          for (var i = 0; i < bstr.length; i++) u8arr[i] = bstr.charCodeAt(i);
          var blob = new Blob([u8arr], { type: mime });
          resolve({ blob: blob, mimeType: mime, size: blob.size });
        });
      });
    }

    if (isPddpicDomain) {
      return tryFetch().catch(function () {
        return tryViaBackground();
      });
    } else {
      return tryViaBackground().then(function (result) {
        if (result) return result;
        return tryFetch();
      });
    }
  }

  function cleanImageUrl(url) {
    try {
      var u = new URL(url);
      if (u.hostname.includes('pddpic.com')) {
        var cleaned = url.split('?')[0];
        if (cleaned !== url) {
          console.log('[PDD填充插件] 剥离CDN参数: ' + url + ' → ' + cleaned);
        }
        return cleaned;
      }
      return url;
    } catch (e) {
      return url;
    }
  }

  function checkImageDimensions(file) {
    return new Promise(function (resolve) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () {
        URL.revokeObjectURL(url);
        var w = img.naturalWidth;
        var h = img.naturalHeight;
        var ratio = w / h;
        var validSize = w >= 480 && h >= 480;
        var validFileSize = file.size <= 3 * 1024 * 1024;
        console.log('[PDD填充插件] 图片尺寸: ' + w + 'x' + h + ', 比例: ' + ratio.toFixed(3) + ', 大小: ' + (file.size / 1024).toFixed(1) + 'KB, 尺寸合规: ' + validSize + ', 文件大小合规: ' + validFileSize);
        resolve({ width: w, height: h, valid: validSize && validFileSize });
      };
      img.onerror = function () {
        URL.revokeObjectURL(url);
        console.warn('[PDD填充插件] 无法读取图片尺寸');
        resolve({ width: 0, height: 0, valid: false });
      };
      img.src = url;
    });
  }

  function findImageFileInput() {
    var pictureArea = document.querySelector('#picture') || document.querySelector('#basic\\.carousel_gallery');
    if (pictureArea) {
      var input = pictureArea.querySelector('input[type="file"][accept*="image"]');
      if (input) return input;
    }
    var inputs = Array.prototype.slice.call(document.querySelectorAll('input[type="file"]'));
    var imageInputs = inputs.filter(function (input) {
      var accept = input.getAttribute('accept') || '';
      return !accept || accept.includes('image') || accept.includes('jpg') || accept.includes('jpeg') || accept.includes('png');
    });
    if (imageInputs.length === 0) return null;

    function visibleBox(el) {
      var current = el;
      for (var depth = 0; current && depth < 6; depth++, current = current.parentElement) {
        var rect = current.getBoundingClientRect();
        if (rect.width > 20 && rect.height > 20) return rect;
      }
      return el.getBoundingClientRect();
    }

    var bodyText = document.body && (document.body.innerText || document.body.textContent || '');
    if (bodyText && bodyText.includes('商品主图')) {
      var scored = imageInputs.map(function (input, index) {
        var rect = visibleBox(input);
        var ancestor = input;
        var text = '';
        for (var depth = 0; ancestor && depth < 7; depth++, ancestor = ancestor.parentElement) {
          text += ' ' + (ancestor.innerText || ancestor.textContent || '');
        }
        var score = index;
        if (text.includes('商品主图') || text.includes('上传图片') || text.includes('轮播图')) score -= 1000;
        score += Math.max(0, rect.top);
        return { input: input, score: score };
      }).sort(function (a, b) {
        return a.score - b.score;
      });
      return scored[0].input;
    }

    return imageInputs[0] || null;
  }

  function findDetailImageFileInput() {
    var tracked = document.querySelector('input[data-tracking-click-viewid="detail_img_localfile_upload"]');
    if (tracked) return tracked;

    var container = document.querySelector('[class*="quick_decoration_v2_operateContainer"]');
    if (container) {
      var input = container.querySelector('input[type="file"][accept*="image"]');
      if (input) return input;
    }

    var spans = document.querySelectorAll('span[class*="quick_decoration_v2_editTextTitle"]');
    for (var i = 0; i < spans.length; i++) {
      var span = spans[i];
      if (span.textContent.includes('快捷编辑')) {
        var section = span.closest('[class*="quick_decoration_v2_operateContainer"]');
        if (section) {
          var input = section.querySelector('input[type="file"][accept*="image"]');
          if (input) return input;
        }
      }
    }

    return null;
  }

  function findSkuImageFileInput() {
    var container = document.querySelector('.batch-set.batch-sku-thumb') || document.querySelector('[class*="batch-sku-thumb"]');
    if (container) {
      var input = container.querySelector('input[type="file"][accept*="image"]');
      if (input) return input;
    }

    var materialContainer = document.querySelector('[class*="MaterialModalButton_materialContainer"]');
    if (materialContainer) {
      var input = materialContainer.querySelector('input[type="file"][accept*="image"]');
      if (input) return input;
    }

    var tracked = document.querySelector('[data-tracking-viewid="attr_pictureadd"]');
    if (tracked) {
      var input = tracked.querySelector('input[type="file"][accept*="image"]');
      if (input) return input;
    }

    return null;
  }

  /**
   * 等待图片上传完成（平台侧处理）
   * 检测逻辑：
   * 1. 等待上传中的 loading/progress 指示器消失
   * 2. 如果出现上传失败提示且长时间不消失，尝试删除失败图片并重试
   * @param {number} expectedCount - 期望上传的图片数量
   * @param {Function} delay - delay 函数
   * @param {Object} Toast - Toast 提示对象
   * @param {Function} [areaFinder] - 可选，自定义上传区域查找函数
   * @returns {Promise<boolean>} 是否全部上传成功
   */
  function waitForImageUploadComplete(expectedCount, delay, Toast, areaFinder) {
    var maxWait = 120000; // 最多等2分钟（大量图片+慢网络）
    var checkInterval = 1500;
    var startTime = Date.now();
    var retryAttempted = false;
    var failureStableStart = 0; // 失败提示稳定出现的起始时间
    var failureStableThreshold = 15000; // 失败提示持续15秒则认为需要重试

    return new Promise(function (resolve) {
      function check() {
        var elapsed = Date.now() - startTime;

        // 查找图片上传区域
        var pictureArea;
        if (areaFinder) {
          pictureArea = areaFinder();
        } else {
          pictureArea = document.querySelector('#picture') ||
                        document.querySelector('#basic\\.carousel_gallery') ||
                        document.querySelector('[id="goodsCarouselId"]') ||
                        document.querySelector('[id="goodsCarousel"]') ||
                        document.querySelector('[data-tracking-viewid="el_upload_wheel_chart"]');
        }

        // 检测上传中的 loading 指示器（仅检测真正的上传进度/旋转动画）
        var hasLoading = false;
        if (pictureArea) {
          // 只检测正在旋转的 Beast Core Spin 组件（Spn_spinning_ 表示正在加载中）
          var spinningEls = pictureArea.querySelectorAll('[class*="Spn_spinning"]');
          for (var spi = 0; spi < spinningEls.length; spi++) {
            if (spinningEls[spi].offsetParent !== null) {
              hasLoading = true;
              break;
            }
          }
          // 上传中的 progress bar 或 uploading 状态
          if (!hasLoading) {
            hasLoading = !!(
              pictureArea.querySelector('[class*="uploading"]') ||
              pictureArea.querySelector('[class*="uploadProgress"]') ||
              pictureArea.querySelector('[class*="upload-progress"]')
            );
          }
        }

        // 检测上传失败提示
        var hasFailure = false;
        var failEls = [];
        if (pictureArea) {
          // 失败/错误提示区域
          var errorEls = pictureArea.querySelectorAll('[class*="error"], [class*="fail"], [class*="retry"]');
          for (var i = 0; i < errorEls.length; i++) {
            if (errorEls[i].offsetParent !== null) {
              hasFailure = true;
              failEls.push(errorEls[i]);
            }
          }
        }

        // 全局 Toast/Notice 也可能提示上传失败
        if (!hasFailure) {
          var notices = document.querySelectorAll('[class*="Notice_"], [class*="notice_"], [class*="Toast_"], [class*="Message_"]');
          for (var ni = 0; ni < notices.length; ni++) {
            var noticeText = notices[ni].textContent || '';
            if ((noticeText.includes('上传失败') || noticeText.includes('上传错误') || noticeText.includes('重新上传')) && notices[ni].offsetParent !== null) {
              hasFailure = true;
              break;
            }
          }
        }

        // 检测已成功上传的图片缩略图数量
        var uploadedCount = 0;
        if (pictureArea) {
          // PDD 上传的图片以 MaterialModalButton_v2_imgContainer 容器展示
          // 或者以 background-image 方式展示在 imageBox 中
          var imgContainers = pictureArea.querySelectorAll('[class*="MaterialModalButton_v2_imgContainer"], [class*="MaterialModalButton_v2_imageBox"]');
          uploadedCount = imgContainers.length;
          // 详情图区域：上传后的图片可能使用不同的展示容器
          if (uploadedCount === 0) {
            var detailContainers = pictureArea.querySelectorAll('[class*="quick_decoration_v2_img"], [class*="decoration_v2_img"], [class*="imgItem"], [class*="imageItem"]');
            for (var dci = 0; dci < detailContainers.length; dci++) {
              if (detailContainers[dci].offsetParent !== null) uploadedCount++;
            }
          }
          // 兜底：也检查传统 img 标签
          if (uploadedCount === 0) {
            var imgTags = pictureArea.querySelectorAll('img[src*="pddpic.com"], img[src*="pinduoduo.com"], img[src*="pfs.pinduoduo.com"]');
            uploadedCount = imgTags.length;
          }
          // 再兜底：检查有 background-image 包含 pdd 域名的 div
          if (uploadedCount === 0) {
            var allDivs = pictureArea.querySelectorAll('div[style*="background-image"]');
            for (var di = 0; di < allDivs.length; di++) {
              var bgStyle = allDivs[di].style.backgroundImage || '';
              if (bgStyle.indexOf('pddpic.com') !== -1 || bgStyle.indexOf('pinduoduo.com') !== -1) {
                uploadedCount++;
              }
            }
          }
        }

        console.log('[PDD填充插件] 上传状态检测 (' + Math.round(elapsed / 1000) + 's): loading=' + hasLoading + ', failure=' + hasFailure + ', uploaded=' + uploadedCount + '/' + expectedCount);

        // 优先判断：如果已检测到上传成功的图片，直接返回成功
        // （不再被无关的 loading 指示器阻塞）
        if (uploadedCount > 0 && !hasFailure) {
          failureStableStart = 0;
          console.log('[PDD填充插件] 图片上传完成，已上传 ' + uploadedCount + ' 张');
          resolve(true);
          return;
        }

        // 宽松模式：使用自定义 areaFinder 时（详情图等场景），
        // 若长时间无 loading/failure 且未检测到上传结果，视为上传成功
        if (areaFinder && !hasLoading && !hasFailure && uploadedCount === 0 && elapsed > 15000) {
          console.log('[PDD填充插件] 详情图模式：15秒内无异常指示器，视为上传成功');
          resolve(true);
          return;
        }

        // 正在上传中（无已上传图片时才阻塞等待）
        if (hasLoading && uploadedCount === 0) {
          failureStableStart = 0;
          if (elapsed < maxWait) {
            setTimeout(check, checkInterval);
          } else {
            console.warn('[PDD填充插件] 图片上传超时，仍有 loading 指示器');
            resolve(false);
          }
          return;
        }

        // 有失败提示
        if (hasFailure) {
          if (failureStableStart === 0) {
            failureStableStart = Date.now();
          }

          var failureDuration = Date.now() - failureStableStart;

          if (failureDuration < failureStableThreshold) {
            // 失败提示还不够稳定，可能是临时的，继续等
            if (elapsed < maxWait) {
              setTimeout(check, checkInterval);
            } else {
              resolve(false);
            }
            return;
          }

          // 失败提示已持续足够长时间
          if (!retryAttempted) {
            retryAttempted = true;
            console.log('[PDD填充插件] 上传失败提示持续 ' + Math.round(failureDuration / 1000) + 's，尝试删除失败图片并重试');
            if (Toast) Toast.show('检测到上传失败，正在重试...', 'warning', 5000);

            // 尝试点击失败图片的删除按钮
            deleteFailedImages(pictureArea);

            // 等待删除完成后继续检测
            failureStableStart = 0;
            setTimeout(check, 3000);
            return;
          }

          // 已重试过，不再重试
          console.warn('[PDD填充插件] 重试后仍有上传失败');
          resolve(false);
          return;
        }

        // 无 loading、无失败 => 检查是否有足够的已上传图片
        failureStableStart = 0;

        if (uploadedCount > 0) {
          // 有图片已上传成功
          console.log('[PDD填充插件] 图片上传完成，已上传 ' + uploadedCount + ' 张');
          resolve(true);
          return;
        }

        // 还没有任何缩略图出现，可能还在处理中
        if (elapsed < maxWait) {
          setTimeout(check, checkInterval);
        } else {
          console.warn('[PDD填充插件] 图片上传超时，未检测到已上传图片');
          resolve(false);
        }
      }

      // 初始等待2秒让平台开始处理
      setTimeout(check, 2000);
    });
  }

  /**
   * 尝试删除上传失败的图片
   */
  function deleteFailedImages(pictureArea) {
    if (!pictureArea) return;

    // 查找包含失败标记的图片项
    var items = pictureArea.querySelectorAll('[class*="uploadImgItem"], [class*="imgItem"], [class*="imageItem"]');
    for (var i = 0; i < items.length; i++) {
      var item = items[i];
      var hasError = item.querySelector('[class*="error"]') || item.querySelector('[class*="fail"]') || item.querySelector('[class*="retry"]');
      if (hasError && hasError.offsetParent !== null) {
        // 查找删除按钮
        var deleteBtn = item.querySelector('[class*="delete"]') || item.querySelector('[class*="close"]') || item.querySelector('[class*="remove"]');
        if (deleteBtn) {
          console.log('[PDD填充插件] 删除失败图片项');
          deleteBtn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        }
      }
    }

    // 也尝试点击全局的"重新上传"按钮
    var retryBtns = pictureArea.querySelectorAll('button, span, a');
    for (var j = 0; j < retryBtns.length; j++) {
      var text = retryBtns[j].textContent.trim();
      if ((text === '重新上传' || text === '重试') && retryBtns[j].offsetParent !== null) {
        console.log('[PDD填充插件] 点击重新上传按钮');
        retryBtns[j].dispatchEvent(new MouseEvent('click', { bubbles: true }));
      }
    }
  }

  function uploadImages(imageItems, options) {
    options = options || {};
    var Toast = options.Toast;
    var delay = options.delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };

    if (!Array.isArray(imageItems) || imageItems.length === 0) {
      if (Toast) Toast.show('收到的图片数据为空或格式不正确', 'error');
      return Promise.resolve();
    }

    if (Toast) Toast.show('开始上传 ' + imageItems.length + ' 张图片...', 'info', 3000);
    console.log('[PDD填充插件] 开始上传图片，数量:', imageItems.length);

    var fileInput = findImageFileInput();
    if (!fileInput) {
      if (Toast) Toast.show('未找到图片上传入口', 'error');
      console.error('[PDD填充插件] 未找到 file input 元素');
      return Promise.resolve();
    }
    console.log('[PDD填充插件] 找到 file input:', fileInput, 'accept:', fileInput.accept);

    var self = this;
    var files = [];
    var skippedCount = 0;

    function processImage(index) {
      if (index >= imageItems.length) {
        if (files.length === 0) {
          if (Toast) Toast.show('没有符合要求的图片可上传', 'error');
          return Promise.resolve();
        }

        var dataTransfer = new DataTransfer();
        for (var fi = 0; fi < files.length; fi++) {
          dataTransfer.items.add(files[fi]);
        }

        fileInput.files = dataTransfer.files;
        fileInput.dispatchEvent(new Event('change', { bubbles: true }));
        fileInput.dispatchEvent(new Event('input', { bubbles: true }));

        console.log('[PDD填充插件] 已触发图片上传, 等待平台处理完成...');
        if (Toast) Toast.show('图片上传中，等待平台处理...', 'info', 10000);

        return waitForImageUploadComplete(files.length, delay, Toast).then(function (uploadOk) {
          var detail = skippedCount > 0
            ? '合规上传: ' + files.length + ' 张, 跳过不合规: ' + skippedCount + ' 张'
            : '成功上传: ' + files.length + '/' + imageItems.length + ' 张';

          if (uploadOk) {
            if (Toast) Toast.show('PDD图片上传完成', 'success', 6000);
          } else {
            if (Toast) Toast.show('部分图片上传可能失败，请检查', 'warning', 6000);
          }
          if (Toast) Toast.show(detail, 'info', 6000);

          console.log('[PDD填充插件] PDD图片上传完成, 全部成功:', uploadOk);
          console.log('[PDD填充插件] ' + detail);
        });
      }

      var item = imageItems[index];
      var rawUrl = typeof item === 'string' ? item : item.url;
      var declaredSize = typeof item === 'object' && item.size ? item.size : null;
      var url = cleanImageUrl(rawUrl);

      if (declaredSize) {
        var parts = declaredSize.split('x');
        var pw = parseInt(parts[0], 10);
        var ph = parseInt(parts[1], 10);
        if (pw && ph && (pw < 480 || ph < 480)) {
          console.warn('[PDD填充插件] 图片 ' + (index + 1) + ' 声明尺寸 ' + declaredSize + ' 不符合PDD要求（>=480px），已跳过');
          if (Toast) Toast.show('图片 ' + (index + 1) + ' 不符合要求（' + declaredSize + '），已跳过', 'warning', 3000);
          skippedCount++;
          return processImage(index + 1);
        }
      }

      if (Toast) Toast.show('正在获取图片 (' + (index + 1) + '/' + imageItems.length + ')...', 'info', 2000);

      return fetchImageDirect(url).then(function (result) {
        if (!result) {
          console.warn('[PDD填充插件] 第 ' + (index + 1) + ' 张图片获取失败: ' + url);
          return processImage(index + 1);
        }

        var ext = result.mimeType === 'image/png' ? 'png' : 'jpg';
        var fileName = 'image_' + (index + 1) + '.' + ext;
        var file = new File([result.blob], fileName, { type: result.mimeType });

        return checkImageDimensions(file).then(function (dims) {
          if (!dims.valid) {
            console.warn('[PDD填充插件] 图片 ' + (index + 1) + ' 不符合PDD要求（' + dims.width + 'x' + dims.height + ', ' + (file.size / 1024).toFixed(1) + 'KB），已跳过');
            if (Toast) Toast.show('图片 ' + (index + 1) + ' 不符合要求（' + dims.width + 'x' + dims.height + '），已跳过', 'warning', 3000);
            skippedCount++;
          } else {
            files.push(file);
            console.log('[PDD填充插件] 图片 ' + (index + 1) + ' 获取成功: ' + fileName + ' (' + (file.size / 1024).toFixed(1) + 'KB, ' + dims.width + 'x' + dims.height + ')');
          }
          return processImage(index + 1);
        });
      });
    }

    return processImage(0);
  }

  function uploadDetailImages(imageDataArray, options) {
    options = options || {};
    var Toast = options.Toast;
    var delay = options.delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };

    if (!Array.isArray(imageDataArray) || imageDataArray.length === 0) {
      if (Toast) Toast.show('收到的详情图数据为空或格式不正确', 'error');
      return Promise.resolve();
    }

    if (Toast) Toast.show('开始上传 ' + imageDataArray.length + ' 张详情图...', 'info', 3000);
    console.log('[PDD填充插件] 开始上传详情图，数量:', imageDataArray.length);

    var fileInput = findDetailImageFileInput();
    if (!fileInput) {
      if (Toast) Toast.show('未找到详情图上传入口', 'error');
      console.error('[PDD填充插件] 未找到详情图 file input 元素');
      return Promise.resolve();
    }
    console.log('[PDD填充插件] 找到详情图 file input:', fileInput, 'accept:', fileInput.accept);

    var files = [];
    var failedCount = 0;

    function processDetailImage(index) {
      if (index >= imageDataArray.length) {
        if (files.length === 0) {
          if (Toast) Toast.show('没有可上传的详情图', 'error');
          return Promise.resolve();
        }

        var dataTransfer = new DataTransfer();
        for (var fi = 0; fi < files.length; fi++) {
          dataTransfer.items.add(files[fi]);
        }

        fileInput.files = dataTransfer.files;
        fileInput.dispatchEvent(new Event('change', { bubbles: true }));
        fileInput.dispatchEvent(new Event('input', { bubbles: true }));

        console.log('[PDD填充插件] 已触发详情图上传, 等待平台处理完成...');
        if (Toast) Toast.show('详情图上传中，等待平台处理...', 'info', 10000);

        // 详情图上传区域查找器（返回较宽的父容器以包含预览区域）
        var detailAreaFinder = function () {
          // 策略1: 快捷编辑操作容器 → 取其父级 section 以包含预览区
          var container = document.querySelector('[class*="quick_decoration_v2_operateContainer"]');
          if (container) return container.closest('section') || container.parentElement || container;
          // 策略2: 通过详情图上传 input 定位
          var tracked = document.querySelector('[data-tracking-click-viewid="detail_img_localfile_upload"]');
          if (tracked) return tracked.closest('section') || tracked.closest('[class*="container"]') || tracked.parentElement;
          // 策略3: 快捷编辑文本定位
          var spans = document.querySelectorAll('span[class*="quick_decoration_v2"]');
          for (var si = 0; si < spans.length; si++) {
            if (spans[si].textContent.includes('快捷编辑')) {
              var sec = spans[si].closest('section') || spans[si].closest('[class*="container"]');
              if (sec) return sec;
            }
          }
          // 策略4: 详情描述区域
          return document.querySelector('#descriptionId') || document.querySelector('[id*="description"]');
        };

        return waitForImageUploadComplete(files.length, delay, Toast, detailAreaFinder).then(function (uploadOk) {
          var summary = failedCount > 0
            ? '成功上传: ' + files.length + ' 张, 失败: ' + failedCount + ' 张'
            : '成功上传: ' + files.length + '/' + imageDataArray.length + ' 张';

          if (uploadOk) {
            if (Toast) Toast.show('PDD详情图上传完成', 'success', 6000);
          } else {
            if (Toast) Toast.show('部分详情图上传可能失败，请检查', 'warning', 6000);
          }
          if (Toast) Toast.show(summary, 'info', 6000);

          console.log('[PDD填充插件] PDD详情图上传完成, 全部成功:', uploadOk);
          console.log('[PDD填充插件] ' + summary);
        });
      }

      var item = imageDataArray[index];
      var url = item.url;
      var fileName = item.name || 'detail_' + (index + 1) + '.jpg';

      if (Toast) Toast.show('正在获取详情图 (' + (index + 1) + '/' + imageDataArray.length + ')...', 'info', 2000);

      return fetchImageDirect(url).then(function (result) {
        if (!result) {
          console.warn('[PDD填充插件] 详情图 ' + (index + 1) + ' 获取失败: ' + url);
          failedCount++;
          return processDetailImage(index + 1);
        }

        var mimeType = result.mimeType || 'image/jpeg';
        var file = new File([result.blob], fileName, { type: mimeType });

        if (file.size > 3 * 1024 * 1024) {
          console.warn('[PDD填充插件] 详情图 ' + (index + 1) + ' 文件过大 (' + (file.size / 1024 / 1024).toFixed(1) + 'MB)，已跳过');
          if (Toast) Toast.show('详情图 ' + (index + 1) + ' 文件过大，已跳过', 'warning', 3000);
          failedCount++;
        } else {
          files.push(file);
          console.log('[PDD填充插件] 详情图 ' + (index + 1) + ' 获取成功: ' + fileName + ' (' + (file.size / 1024).toFixed(1) + 'KB)');
        }

        return processDetailImage(index + 1);
      });
    }

    return processDetailImage(0);
  }

  function uploadSkuImages(imageDataArray, options) {
    options = options || {};
    var Toast = options.Toast;
    var delay = options.delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };

    if (!Array.isArray(imageDataArray) || imageDataArray.length === 0) {
      if (Toast) Toast.show('收到的SKU图数据为空或格式不正确', 'error');
      return Promise.resolve();
    }

    if (Toast) Toast.show('开始上传 ' + imageDataArray.length + ' 张SKU图...', 'info', 3000);
    console.log('[PDD填充插件] 开始上传SKU图，数量:', imageDataArray.length);

    var fileInput = findSkuImageFileInput();
    if (!fileInput) {
      if (Toast) Toast.show('未找到SKU图上传入口', 'error');
      console.error('[PDD填充插件] 未找到SKU图 file input 元素');
      return Promise.resolve();
    }
    console.log('[PDD填充插件] 找到SKU图 file input:', fileInput, 'accept:', fileInput.accept);

    var files = [];
    var failedCount = 0;

    function processSkuImage(index) {
      if (index >= imageDataArray.length) {
        if (files.length === 0) {
          if (Toast) Toast.show('没有可上传的SKU图', 'error');
          return Promise.resolve();
        }

        var dataTransfer = new DataTransfer();
        for (var fi = 0; fi < files.length; fi++) {
          dataTransfer.items.add(files[fi]);
        }

        fileInput.files = dataTransfer.files;
        fileInput.dispatchEvent(new Event('change', { bubbles: true }));
        fileInput.dispatchEvent(new Event('input', { bubbles: true }));

        return delay(500).then(function () {
          if (Toast) Toast.show('PDD SKU图上传完成', 'success', 6000);
          var summary = failedCount > 0
            ? '成功上传: ' + files.length + ' 张, 失败: ' + failedCount + ' 张'
            : '成功上传: ' + files.length + '/' + imageDataArray.length + ' 张';
          if (Toast) Toast.show(summary, 'info', 6000);

          console.log('[PDD填充插件] PDD SKU图上传完成');
          console.log('[PDD填充插件] ' + summary);
        });
      }

      var item = imageDataArray[index];
      var url = item.url;
      var fileName = item.name || 'sku_' + (index + 1) + '.jpg';

      if (Toast) Toast.show('正在获取SKU图 (' + (index + 1) + '/' + imageDataArray.length + ')...', 'info', 2000);

      return fetchImageDirect(url).then(function (result) {
        if (!result) {
          console.warn('[PDD填充插件] SKU图 ' + (index + 1) + ' 获取失败: ' + url);
          failedCount++;
          return processSkuImage(index + 1);
        }

        var mimeType = result.mimeType || 'image/jpeg';
        var file = new File([result.blob], fileName, { type: mimeType });

        if (file.size > 3 * 1024 * 1024) {
          console.warn('[PDD填充插件] SKU图 ' + (index + 1) + ' 文件过大 (' + (file.size / 1024 / 1024).toFixed(1) + 'MB)，已跳过');
          if (Toast) Toast.show('SKU图 ' + (index + 1) + ' 文件过大，已跳过', 'warning', 3000);
          failedCount++;
        } else {
          files.push(file);
          console.log('[PDD填充插件] SKU图 ' + (index + 1) + ' 获取成功: ' + fileName + ' (' + (file.size / 1024).toFixed(1) + 'KB)');
        }

        return processSkuImage(index + 1);
      });
    }

    return processSkuImage(0);
  }

  return {
    fetchImageDirect: fetchImageDirect,
    cleanImageUrl: cleanImageUrl,
    checkImageDimensions: checkImageDimensions,
    findImageFileInput: findImageFileInput,
    findDetailImageFileInput: findDetailImageFileInput,
    findSkuImageFileInput: findSkuImageFileInput,
    uploadImages: uploadImages,
    uploadDetailImages: uploadDetailImages,
    uploadSkuImages: uploadSkuImages
  };
}));
