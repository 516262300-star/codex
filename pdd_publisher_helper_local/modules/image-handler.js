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
      return findPrefillMainImageFileInput() || imageInputs[0] || null;
    }

    return imageInputs[0] || null;
  }

  function findPrefillMainImageFileInput() {
    var inputs = Array.prototype.slice.call(document.querySelectorAll('input[type="file"]'));
    var imageInputs = inputs.filter(function (input) {
      var accept = (input.getAttribute('accept') || '').toLowerCase();
      return !accept || accept.includes('image') || accept.includes('jpg') || accept.includes('jpeg') || accept.includes('png') || accept.includes('webp');
    });
    if (imageInputs.length === 0) return null;

    function visibleBox(el) {
      var current = el;
      for (var depth = 0; current && depth < 8; depth++, current = current.parentElement) {
        var rect = current.getBoundingClientRect();
        if (rect.width > 20 && rect.height > 20) return rect;
      }
      return el.getBoundingClientRect();
    }

    function scoreInput(input, index) {
      var score = index;
      var text = '';
      var current = input;
      for (var depth = 0; current && depth < 10; depth++, current = current.parentElement) {
        text += ' ' + (current.innerText || current.textContent || '');
        if (current.id === 'goodsCarousel' || current.id === 'goodsCarouselId') score -= 5000;
        if (current.id === 'picture' || current.id === 'basic.carousel_gallery') score -= 1500;
      }
      if (text.includes('商品主图')) score -= 3000;
      if (text.includes('上传图片')) score -= 1500;
      if (text.includes('轮播图')) score -= 1000;
      if (text.includes('商品视频')) score += 4000;
      if (text.includes('商品讲解视频')) score += 4000;
      if (text.includes('详情图') || text.includes('商品详情')) score += 3000;
      if (text.includes('规格图') || text.includes('SKU')) score += 3000;

      var rect = visibleBox(input);
      score += Math.max(0, rect.top);
      score += Math.max(0, rect.left) / 1000;
      return score;
    }

    return imageInputs.map(function (input, index) {
      return { input: input, score: scoreInput(input, index) };
    }).sort(function (a, b) {
      return a.score - b.score;
    })[0].input;
  }

  function findStrictMainImageArea() {
    return document.querySelector('#goodsCarousel') ||
           document.querySelector('#goodsCarouselId') ||
           document.querySelector('#picture') ||
           document.querySelector('#basic\\.carousel_gallery') ||
           document.querySelector('[data-tracking-viewid="el_upload_wheel_chart"]') ||
           findUploadAreaNearText(['商品主图', '上传商品轮播图', '轮播图']);
  }

  function findPrefillMainImageArea() {
    return findStrictMainImageArea() || document.body;
  }

  function findVisibleTextControl(texts) {
    texts = Array.isArray(texts) ? texts : [texts];
    var normalized = texts.map(function (text) { return normalizeText(text); });
    var controls = Array.prototype.slice.call(document.querySelectorAll('button, [role="button"], label, div, span, a'));
    var best = null;
    for (var i = 0; i < controls.length; i++) {
      var el = controls[i];
      if (!isElementVisible(el)) continue;
      var text = normalizeText(el.innerText || el.textContent || '');
      if (normalized.indexOf(text) < 0) continue;
      var rect = el.getBoundingClientRect();
      var score = text.length + rect.width * rect.height / 1000;
      if (!best || score < best.score) best = { el: el, score: score };
    }
    return best && best.el;
  }

  function activatePrefillMainImageUpload(options) {
    options = options || {};
    var delay = options.delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };
    if (findPrefillMainImageFileInput()) return Promise.resolve(true);

    var trigger = findVisibleTextControl(['上传图片']);
    if (!trigger) return Promise.resolve(false);
    trigger.dispatchEvent(new MouseEvent('click', { bubbles: true }));

    return delay(500).then(function () {
      if (findPrefillMainImageFileInput()) return true;
      var localTrigger = findVisibleTextControl(['本地上传', '上传本地图片', '本地图片']);
      if (localTrigger) localTrigger.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      var startedAt = Date.now();
      return new Promise(function (resolve) {
        function check() {
          if (findPrefillMainImageFileInput()) {
            resolve(true);
            return;
          }
          if (Date.now() - startedAt >= 4000) {
            resolve(false);
            return;
          }
          delay(200).then(check);
        }
        check();
      });
    });
  }

  function findMainVideoFileInput() {
    var area = findPrefillMainImageArea();
    var scopedInputs = area ? Array.prototype.slice.call(area.querySelectorAll('input[type="file"]')) : [];

    function isVideoInput(input) {
      var accept = (input.getAttribute('accept') || '').toLowerCase();
      return !accept || accept.includes('video') || accept.includes('mp4') || accept.includes('mov') || accept.includes('webm') || accept.includes('m4v');
    }

    function scoreInput(input, index) {
      var score = index;
      var text = '';
      var current = input;
      for (var depth = 0; current && depth < 10; depth++, current = current.parentElement) {
        text += ' ' + (current.innerText || current.textContent || '');
        if (current.id === 'goodsCarousel' || current.id === 'goodsCarouselId') score -= 5000;
        if (current.id === 'picture' || current.id === 'basic.carousel_gallery') score -= 2500;
      }
      if (text.includes('主图') || text.includes('轮播图') || text.includes('视频')) score -= 1500;
      if (text.includes('商品讲解视频') || text.includes('讲解视频')) score += 5000;
      if (text.includes('详情图') || text.includes('商品详情') || text.includes('规格图') || text.includes('SKU')) score += 4000;
      var rect = input.getBoundingClientRect();
      score += Math.max(0, rect.top);
      return score;
    }

    var videoInputs = scopedInputs.filter(isVideoInput);
    if (videoInputs.length > 0) {
      return videoInputs.map(function (input, index) {
        return { input: input, score: scoreInput(input, index) };
      }).sort(function (a, b) {
        return a.score - b.score;
      })[0].input;
    }

    var allInputs = Array.prototype.slice.call(document.querySelectorAll('input[type="file"]')).filter(isVideoInput);
    var candidates = allInputs.filter(function (input) {
      var text = '';
      var current = input;
      for (var depth = 0; current && depth < 10; depth++, current = current.parentElement) {
        text += ' ' + (current.innerText || current.textContent || '');
      }
      return (text.includes('商品主图') || text.includes('主图') || text.includes('轮播图')) &&
             !text.includes('商品讲解视频') &&
             !text.includes('详情图') &&
             !text.includes('规格图') &&
             !text.includes('SKU');
    });
    if (candidates.length === 0) return null;
    return candidates.map(function (input, index) {
      return { input: input, score: scoreInput(input, index) };
    }).sort(function (a, b) {
      return a.score - b.score;
    })[0].input;
  }

  function activateMainVideoUploadTab(options) {
    options = options || {};
    var delay = options.delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };
    var area = findStrictMainImageArea();
    if (!area) return Promise.resolve(false);
    if (findMainVideoFileInput()) return Promise.resolve(true);

    var controls = Array.prototype.slice.call(area.querySelectorAll('button, [role="button"], span, div, a'));
    var best = null;
    for (var i = 0; i < controls.length; i++) {
      var el = controls[i];
      if (el.offsetParent === null) continue;
      var text = (el.innerText || el.textContent || '').replace(/\s+/g, '').trim();
      if (!text) continue;
      var score = 0;
      if (text === '视频' || text === '上传视频') score -= 3000;
      else if (text.includes('视频')) score -= 1000;
      else continue;
      if (text.includes('讲解') || text.includes('详情') || text.includes('SKU')) score += 5000;
      var rect = el.getBoundingClientRect();
      score += Math.max(0, rect.top) + Math.max(0, rect.left) / 1000 + text.length;
      if (!best || score < best.score) best = { el: el, score: score };
    }

    if (!best) return Promise.resolve(false);
    best.el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return delay(600).then(function () { return true; });
  }

  function isElementVisible(el) {
    if (!el) return false;
    var style = window.getComputedStyle(el);
    var rect = el.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
  }

  function normalizeText(text) {
    return String(text || '').replace(/\s+/g, '').trim();
  }

  function materialSelectedVideoCount(modal) {
    if (!modal) return null;
    var text = normalizeText(modal.innerText || modal.textContent || '');
    var match = text.match(/已(?:选|选择)(\d+)(?:张|个)/);
    return match ? Number(match[1]) : null;
  }

  var lastMaterialVideoError = '';

  function setMaterialVideoError(message) {
    lastMaterialVideoError = String(message || '');
    if (lastMaterialVideoError) {
      console.warn('[PDD填充插件] ' + lastMaterialVideoError);
    }
    return false;
  }

  function getLastMaterialVideoError() {
    return lastMaterialVideoError;
  }

  function clickLikeUser(el) {
    if (!el) return false;
    try {
      if (typeof el.scrollIntoView === 'function') {
        el.scrollIntoView({ block: 'center', inline: 'center' });
      }
      var eventInit = { bubbles: true, cancelable: true, view: window };
      if (typeof PointerEvent === 'function') {
        el.dispatchEvent(new PointerEvent('pointerdown', eventInit));
      }
      el.dispatchEvent(new MouseEvent('mousedown', eventInit));
      el.dispatchEvent(new MouseEvent('mouseup', eventInit));
      if (typeof PointerEvent === 'function') {
        el.dispatchEvent(new PointerEvent('pointerup', eventInit));
      }
      if (typeof el.click === 'function') {
        el.click();
      } else {
        el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
      }
      return true;
    } catch (err) {
      console.warn('[PDD填充插件] 点击图片空间视频卡片失败:', err);
      return false;
    }
  }

  function findMaterialVideoDialog() {
    var nodes = Array.prototype.slice.call(document.querySelectorAll('[role="dialog"], [class*="Modal"], [class*="modal"], body > div'));
    var best = null;
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (!isElementVisible(el)) continue;
      var text = el.innerText || el.textContent || '';
      if (text.includes('图片空间') && text.includes('确认')) {
        var rect = el.getBoundingClientRect();
        var score = rect.width * rect.height;
        if (!best || score > best.score) best = { el: el, score: score };
      }
    }
    return best && best.el;
  }

  function waitForMaterialVideoDialog(delay, maxWait) {
    var start = Date.now();
    maxWait = maxWait || 12000;
    return new Promise(function (resolve) {
      function check() {
        var modal = findMaterialVideoDialog();
        if (modal) {
          resolve(modal);
          return;
        }
        if (Date.now() - start >= maxWait) {
          resolve(null);
          return;
        }
        delay(300).then(check);
      }
      check();
    });
  }

  function findMaterialDialogMediaControl(modal, modeText) {
    if (!modal) return null;
    var modalRect = modal.getBoundingClientRect();
    var target = normalizeText(modeText);
    var nodes = Array.prototype.slice.call(modal.querySelectorAll(
      'select, [role="combobox"], button, [role="button"], [class*="Select"], [class*="select"], span, div'
    ));
    var best = null;
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (!isElementVisible(el)) continue;
      var text = normalizeText(el.innerText || el.textContent || '');
      if (text !== target) continue;
      var rect = el.getBoundingClientRect();
      if (rect.top > modalRect.top + Math.min(150, modalRect.height * 0.25)) continue;
      if (rect.left < modalRect.left + modalRect.width * 0.20) continue;
      if (rect.width > 360 || rect.height > 100) continue;
      var roleBonus = el.matches('select, [role="combobox"], button, [role="button"]') ? -1000 : 0;
      var score = roleBonus + Math.abs(rect.top - (modalRect.top + 55)) + rect.width / 10 + rect.height;
      if (!best || score < best.score) best = { el: el, score: score };
    }
    return best && best.el;
  }

  function materialDialogIsVideoMode(modal) {
    if (!modal) return false;
    var text = normalizeText(modal.innerText || modal.textContent || '');
    return !!findMaterialDialogMediaControl(modal, '视频') ||
           text.includes('仅展示上传成功的视频') ||
           text.includes('请输入视频名称');
  }

  function ensureMaterialDialogVideoMode(modal, delay) {
    var refreshed = findMaterialVideoDialog() || modal;
    if (!refreshed) return Promise.resolve(false);
    if (materialDialogIsVideoMode(refreshed)) return Promise.resolve(true);

    var nativeSelects = Array.prototype.slice.call(refreshed.querySelectorAll('select'));
    for (var si = 0; si < nativeSelects.length; si++) {
      var select = nativeSelects[si];
      var options = Array.prototype.slice.call(select.options || []);
      var videoOption = options.find(function (option) {
        return normalizeText(option.textContent || option.innerText || '') === '视频';
      });
      if (videoOption) {
        select.value = videoOption.value;
        select.dispatchEvent(new Event('input', { bubbles: true }));
        select.dispatchEvent(new Event('change', { bubbles: true }));
        return delay(800).then(function () {
          return materialDialogIsVideoMode(findMaterialVideoDialog() || refreshed);
        });
      }
    }

    var imageControl = findMaterialDialogMediaControl(refreshed, '图片');
    if (!imageControl) return Promise.resolve(false);
    var triggerRect = imageControl.getBoundingClientRect();
    clickLikeUser(imageControl);
    return delay(350).then(function () {
      var optionNodes = Array.prototype.slice.call(document.querySelectorAll(
        '[role="option"], li, [class*="Option"], [class*="option"], span, div'
      ));
      var best = null;
      for (var oi = 0; oi < optionNodes.length; oi++) {
        var option = optionNodes[oi];
        if (!isElementVisible(option) || option === imageControl) continue;
        if (normalizeText(option.innerText || option.textContent || '') !== '视频') continue;
        var rect = option.getBoundingClientRect();
        if (rect.width > 400 || rect.height > 100) continue;
        var roleBonus = option.matches('[role="option"], li') ? -2000 : 0;
        var score = roleBonus + Math.abs(rect.left - triggerRect.left) + Math.abs(rect.top - triggerRect.bottom);
        if (!best || score < best.score) best = { el: option, score: score };
      }
      if (!best) return false;
      clickLikeUser(best.el);
      var startedAt = Date.now();
      return new Promise(function (resolve) {
        function check() {
          var latest = findMaterialVideoDialog() || refreshed;
          if (materialDialogIsVideoMode(latest)) {
            resolve(true);
            return;
          }
          if (Date.now() - startedAt >= 8000) {
            resolve(false);
            return;
          }
          delay(300).then(check);
        }
        delay(300).then(check);
      });
    });
  }

  function closeMaterialVideoDialog(delay) {
    var modal = findMaterialVideoDialog();
    if (!modal) return Promise.resolve(true);
    var controls = Array.prototype.slice.call(modal.querySelectorAll(
      'button, [role="button"], [aria-label], [class*="close"], [class*="Close"]'
    )).filter(isElementVisible);
    var candidates = [];
    var modalRect = modal.getBoundingClientRect();
    for (var i = 0; i < controls.length; i++) {
      var control = controls[i];
      var text = normalizeText(control.innerText || control.textContent || '');
      var aria = normalizeText(control.getAttribute('aria-label') || '');
      var rect = control.getBoundingClientRect();
      var score = Infinity;
      if (text === '取消') score = 0;
      else if (/^(关闭|close)$/i.test(aria)) score = 100;
      else if (/close/i.test(String(control.className || ''))) {
        score = 200 + Math.abs(rect.right - modalRect.right) + Math.abs(rect.top - modalRect.top);
      } else if (rect.width <= 70 && rect.height <= 70 &&
                 Math.abs(rect.right - modalRect.right) <= 45 && Math.abs(rect.top - modalRect.top) <= 45) {
        score = 300 + Math.abs(rect.right - modalRect.right) + Math.abs(rect.top - modalRect.top);
      }
      if (score !== Infinity) candidates.push({ el: control, score: score });
    }
    candidates.sort(function (a, b) { return a.score - b.score; });
    if (!candidates.length) return Promise.resolve(false);

    function attempt(index) {
      if (index >= candidates.length) return Promise.resolve(false);
      var latest = findMaterialVideoDialog();
      if (!latest) return Promise.resolve(true);
      if (!latest.contains(candidates[index].el)) return attempt(index + 1);
      clickLikeUser(candidates[index].el);
      var startedAt = Date.now();
      return new Promise(function (resolve) {
        function check() {
          if (!findMaterialVideoDialog()) {
            resolve(true);
            return;
          }
          if (Date.now() - startedAt >= 2500) {
            resolve(false);
            return;
          }
          delay(250).then(check);
        }
        delay(250).then(check);
      }).then(function (closed) {
        return closed ? true : attempt(index + 1);
      });
    }

    return attempt(0);
  }

  function closeAfterMaterialVideoFailure(delay) {
    return closeMaterialVideoDialog(delay).then(function (closed) {
      if (!closed) {
        throw new Error((lastMaterialVideoError || '视频选择失败') + '；图片空间弹窗无法自动关闭，已停止后续填写');
      }
      return false;
    });
  }

  function findBestVisibleTextElement(container, targetText, options) {
    options = options || {};
    var exact = options.exact !== false;
    var modalRect = container.getBoundingClientRect();
    var nodes = Array.prototype.slice.call(container.querySelectorAll('button, [role="button"], span, div, li, a'));
    var target = normalizeText(targetText);
    var best = null;
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (!isElementVisible(el)) continue;
      var text = normalizeText(el.innerText || el.textContent || '');
      if (!text) continue;
      if (exact ? text !== target : text.indexOf(target) < 0) continue;
      var rect = el.getBoundingClientRect();
      if (options.leftOnly && rect.left > modalRect.left + modalRect.width * 0.38) continue;
      if (options.rightOnly && rect.left < modalRect.left + modalRect.width * 0.22) continue;
      var score = text.length + rect.width / 100 + rect.height / 100 + Math.max(0, rect.top - modalRect.top) / 1000;
      if (!best || score < best.score) best = { el: el, score: score };
    }
    return best && best.el;
  }

  function clickBestVisibleText(container, targetText, options) {
    var el = findBestVisibleTextElement(container, targetText, options);
    if (!el) return false;
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return true;
  }

  function clickMainVideoTrigger(delay) {
    var area = findStrictMainImageArea();
    if (!area) return Promise.resolve(false);
    return activateMainVideoUploadTab({ delay: delay }).then(function () {
      if (findMaterialVideoDialog()) return true;
      area = findStrictMainImageArea() || area;

      var controls = Array.prototype.slice.call(area.querySelectorAll('button, [role="button"], div, span, a'));
      var best = null;
      for (var i = 0; i < controls.length; i++) {
        var el = controls[i];
        if (!isElementVisible(el)) continue;
        var text = normalizeText(el.innerText || el.textContent || '');
        var rect = el.getBoundingClientRect();
        var score = null;
        if (text === '上传视频' || text === '选择视频') score = 0;
        else if (text === '视频') score = 500;
        else if (text.includes('上传视频') || text.includes('选择视频')) score = 500;
        else if (rect.width >= 50 && rect.height >= 50 && text.includes('视频')) score = 1000;
        if (score === null) continue;
        if (text.includes('讲解') || text.includes('详情') || text.includes('SKU')) score += 5000;
        score += Math.max(0, rect.top) + Math.max(0, rect.left) / 1000 + text.length;
        if (!best || score < best.score) best = { el: el, score: score };
      }
      if (!best) return false;
      best.el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      return true;
    });
  }

  function clickVideoTriggerNearText(labels, delay) {
    var area = findUploadAreaNearText(labels);
    if (!area) return Promise.resolve(false);
    var controls = Array.prototype.slice.call(area.querySelectorAll('button, [role="button"], div, span, a'));
    var best = null;
    for (var i = 0; i < controls.length; i++) {
      var el = controls[i];
      if (!isElementVisible(el)) continue;
      var text = normalizeText(el.innerText || el.textContent || '');
      var rect = el.getBoundingClientRect();
      var score = null;
      if (text === '上传视频' || text === '选择视频') score = 0;
      else if (text.includes('上传视频') || text.includes('选择视频')) score = 500;
      else if (rect.width >= 50 && rect.height >= 50 && text.includes('视频')) score = 1000;
      if (score === null) continue;
      score += Math.max(0, rect.top) + Math.max(0, rect.left) / 1000 + text.length;
      if (!best || score < best.score) best = { el: el, score: score };
    }
    if (!best) return Promise.resolve(false);
    best.el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return delay(500).then(function () { return true; });
  }

  function clickMaterialPickerTrigger(labels, delay, allowPortal) {
    var area = labels.indexOf('主图视频') >= 0
      ? findStrictMainImageArea()
      : findUploadAreaNearText(labels);
    if (!area) return Promise.resolve(false);
    var controls = Array.prototype.slice.call(area.querySelectorAll('button, [role="button"], div, span, a'));
    var best = null;
    for (var i = 0; i < controls.length; i++) {
      var el = controls[i];
      if (!isElementVisible(el)) continue;
      var text = normalizeText(el.innerText || el.textContent || '');
      var score = null;
      if (text === '图片空间上传' || text === '从图片空间选择' || text === '图片空间选择') score = 0;
      else if (text.includes('图片空间') && (text.includes('上传') || text.includes('选择'))) score = 500;
      if (score === null) continue;
      if (text.includes('本地上传')) score += 5000;
      var rect = el.getBoundingClientRect();
      score += text.length + Math.max(0, rect.top) + Math.max(0, rect.left) / 1000;
      if (!best || score < best.score) best = { el: el, score: score };
    }
    if (!best && allowPortal) {
      controls = Array.prototype.slice.call(document.querySelectorAll('button, [role="button"], div, span, a'));
      var areaRect = area.getBoundingClientRect();
      for (var j = 0; j < controls.length; j++) {
        var candidate = controls[j];
        if (!isElementVisible(candidate)) continue;
        var candidateText = normalizeText(candidate.innerText || candidate.textContent || '');
        if (candidateText === '图片空间上传' || candidateText === '从图片空间选择' || candidateText === '图片空间选择') {
          var candidateRect = candidate.getBoundingClientRect();
          var candidateScore = Math.abs(candidateRect.left - areaRect.left) +
                               Math.min(Math.abs(candidateRect.top - areaRect.top), Math.abs(candidateRect.top - areaRect.bottom));
          if (!best || candidateScore < best.score) best = { el: candidate, score: candidateScore };
        }
      }
    }
    if (!best) return Promise.resolve(false);
    best.el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return delay(700).then(function () { return true; });
  }

  function navigateMaterialPathInDialog(modal, materialPath, delay) {
    var parts = String(materialPath || '').split(/[\\/]+/).filter(Boolean);
    if (!parts.length) return Promise.resolve(true);
    var chain = Promise.resolve({ ok: true, missing: [] });
    parts.forEach(function (part) {
      chain = chain.then(function (result) {
        var refreshed = findMaterialVideoDialog() || modal;
        var clicked = clickBestVisibleText(refreshed, part, { exact: true, leftOnly: true });
        if (!clicked) clicked = clickBestVisibleText(refreshed, part, { exact: false, leftOnly: true });
        if (!clicked) {
          result.ok = false;
          result.missing.push(part);
        }
        return delay(clicked ? 800 : 100).then(function () { return result; });
      });
    });
    return chain;
  }

  function selectVideoCardInDialog(modal, videoItem, delay) {
    var refreshed = findMaterialVideoDialog() || modal;
    var name = String((videoItem && (videoItem.filename || videoItem.name)) || '');
    var stem = name.replace(/\.[a-z0-9]+$/i, '');
    var probes = [name, stem].filter(function (x) { return normalizeText(x).length >= 2; });
    var matched = null;
    for (var i = 0; i < probes.length; i++) {
      matched = findBestVisibleTextElement(refreshed, probes[i], { exact: true, rightOnly: true });
      if (matched) break;
    }
    if (!matched) {
      for (var pi = 0; pi < probes.length; pi++) {
        matched = findBestVisibleTextElement(refreshed, probes[pi], { exact: false, rightOnly: true });
        if (matched) break;
      }
    }

    if (!matched) {
      var modalBounds = refreshed.getBoundingClientRect();
      var normalizedName = normalizeText(name);
      var normalizedStem = normalizeText(stem);
      var nameNodes = Array.prototype.slice.call(refreshed.querySelectorAll(
        '[title], [aria-label], [data-name], [data-filename], [data-file-name], span, div, p'
      ));
      var bestNameMatch = null;
      for (var ni = 0; ni < nameNodes.length; ni++) {
        var node = nameNodes[ni];
        if (!isElementVisible(node)) continue;
        var nodeRect = node.getBoundingClientRect();
        if (nodeRect.left < modalBounds.left + modalBounds.width * 0.22) continue;
        if (nodeRect.width > 500 || nodeRect.height > 120) continue;
        var values = [
          node.getAttribute('title'),
          node.getAttribute('aria-label'),
          node.getAttribute('data-name'),
          node.getAttribute('data-filename'),
          node.getAttribute('data-file-name'),
          node.innerText,
          node.textContent
        ].map(normalizeText).filter(Boolean);
        var nodeScore = Infinity;
        for (var vi = 0; vi < values.length; vi++) {
          var value = values[vi];
          if ((normalizedName && value === normalizedName) || (normalizedStem && value === normalizedStem)) {
            nodeScore = Math.min(nodeScore, vi < 5 ? 0 : 20);
            continue;
          }
          if ((normalizedName && value.includes(normalizedName)) || (normalizedStem && value.includes(normalizedStem))) {
            nodeScore = Math.min(nodeScore, vi < 5 ? 40 : 60);
            continue;
          }
          var visiblePrefix = value.replace(/(?:\.{3}|…).*$/, '');
          if (visiblePrefix.length >= 8 &&
              ((normalizedName && normalizedName.indexOf(visiblePrefix) === 0) ||
               (normalizedStem && normalizedStem.indexOf(visiblePrefix) === 0))) {
            nodeScore = Math.min(nodeScore, 200 - Math.min(100, visiblePrefix.length));
          }
        }
        if (nodeScore === Infinity) continue;
        nodeScore += nodeRect.width / 100 + nodeRect.height / 100;
        if (!bestNameMatch || nodeScore < bestNameMatch.score) {
          bestNameMatch = { el: node, score: nodeScore };
        }
      }
      matched = bestNameMatch && bestNameMatch.el;
    }

    var modalRect = refreshed.getBoundingClientRect();
    var candidates = [];
    var current = matched;
    for (var depth = 0; current && current !== refreshed && depth < 9; depth++, current = current.parentElement) {
      var currentRect = current.getBoundingClientRect();
      if (currentRect.left >= modalRect.left + modalRect.width * 0.25 &&
          currentRect.width >= 80 && currentRect.width <= 300 &&
          currentRect.height >= 100 && currentRect.height <= 360) {
        candidates.push({
          el: current,
          score: Math.abs(currentRect.width - 150) + Math.abs(currentRect.height - 220)
        });
      }
    }
    candidates.sort(function (a, b) { return a.score - b.score; });

    var card = candidates.length ? candidates[0].el : null;
    if (!card && matched) card = matched;
    if (!card) return Promise.resolve(false);

    var beforeCount = materialSelectedVideoCount(refreshed);
    if (beforeCount !== null && beforeCount > 0) return Promise.resolve(true);

    var cardRect = card.getBoundingClientRect();
    var explicitControls = Array.prototype.slice.call(card.querySelectorAll(
      'input[type="checkbox"], [role="checkbox"], [class*="Checkbox"], [class*="checkbox"], [class*="checkBox"], [class*="CheckBox"]'
    )).filter(isElementVisible).map(function (el) {
      var box = el.getBoundingClientRect();
      return {
        el: el.closest('label') || el,
        score: Math.abs(box.right - cardRect.right) + Math.abs(box.top - cardRect.top)
      };
    }).sort(function (a, b) { return a.score - b.score; });

    var attempts = [];
    explicitControls.forEach(function (item) {
      attempts.push(function () { return clickLikeUser(item.el); });
    });
    [[-16, 18], [-12, 32], [-24, 18]].forEach(function (offset) {
      attempts.push(function () {
        var latestCardRect = card.getBoundingClientRect();
        var target = document.elementFromPoint(latestCardRect.right + offset[0], latestCardRect.top + offset[1]);
        if (!target || !refreshed.contains(target)) return false;
        return clickLikeUser(target);
      });
    });
    attempts.push(function () { return clickLikeUser(card); });
    attempts.push(function () { return clickLikeUser(matched); });

    function runAttempt(index) {
      if (index >= attempts.length) return Promise.resolve(false);
      var clicked = attempts[index]();
      if (!clicked) return runAttempt(index + 1);
      return delay(450).then(function () {
        var latest = findMaterialVideoDialog() || refreshed;
        var selectedCount = materialSelectedVideoCount(latest);
        if (selectedCount !== null) return selectedCount > 0 ? true : runAttempt(index + 1);

        var checked = card.querySelector('input[type="checkbox"]:checked, [role="checkbox"][aria-checked="true"]');
        if (checked) return true;
        return runAttempt(index + 1);
      });
    }

    return runAttempt(0);
  }

  function confirmMaterialVideoDialog(delay) {
    var modal = findMaterialVideoDialog();
    if (!modal) return Promise.resolve(false);
    var buttons = Array.prototype.slice.call(modal.querySelectorAll('button, [role="button"]'));
    var best = null;
    for (var i = 0; i < buttons.length; i++) {
      var btn = buttons[i];
      if (!isElementVisible(btn) || btn.disabled) continue;
      var text = normalizeText(btn.innerText || btn.textContent || '');
      if (text !== '确认') continue;
      var rect = btn.getBoundingClientRect();
      var score = -rect.top + rect.left / 1000;
      if (!best || score > best.score) best = { el: btn, score: score };
    }
    if (!best) return Promise.resolve(false);
    clickLikeUser(best.el);
    var startedAt = Date.now();
    return new Promise(function (resolve) {
      function check() {
        if (!findMaterialVideoDialog()) {
          resolve(true);
          return;
        }
        if (Date.now() - startedAt >= 12000) {
          resolve(false);
          return;
        }
        delay(400).then(check);
      }
      delay(400).then(check);
    });
  }

  function selectVideoFromMaterial(videoItem, labels, options) {
    labels = Array.isArray(labels) ? labels : [labels || '视频'];
    options = options || {};
    var Toast = options.Toast;
    var delay = options.delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };
    var materialPath = videoItem && videoItem.materialPath;
    var videoName = String((videoItem && (videoItem.filename || videoItem.name)) || '视频文件');
    lastMaterialVideoError = '';
    if (!materialPath) return Promise.resolve(setMaterialVideoError('视频素材没有图片空间路径'));
    var labelText = labels[0] || '视频';
    if (Toast) Toast.show('正在从图片空间选择' + labelText + '...', 'info', 3000);

    var isMainVideo = labels.indexOf('主图视频') >= 0;
    var staleDialog = findMaterialVideoDialog();
    var startPromise = staleDialog ? closeMaterialVideoDialog(delay) : Promise.resolve(true);

    return startPromise
      .then(function (staleClosed) {
        if (!staleClosed) {
          setMaterialVideoError(labelText + '：上一次遗留的图片空间弹窗无法自动关闭');
          throw new Error(lastMaterialVideoError + '，已停止后续填写');
        }
        return isMainVideo ? clickMainVideoTrigger(delay) : clickVideoTriggerNearText(labels, delay);
      })
      .then(function (triggered) {
        if (!triggered) {
          setMaterialVideoError(labelText + '：未找到对应的视频上传区域，已停止以避免打开规格图片选择框');
          return false;
        }
        return delay(700).then(function () {
          if (findMaterialVideoDialog()) return true;
          return clickMaterialPickerTrigger(labels, delay, true);
        });
      })
      .then(function (opened) {
        if (!opened) return null;
        return waitForMaterialVideoDialog(delay, 12000);
      })
      .then(function (modal) {
        if (!modal) {
          if (!lastMaterialVideoError) setMaterialVideoError(labelText + '：未打开“图片空间”视频选择弹窗');
          if (Toast) Toast.show('未打开图片空间视频选择弹窗', 'warning', 4000);
          return false;
        }
        var navigationResult = { ok: true, missing: [] };
        return ensureMaterialDialogVideoMode(modal, delay).then(function (videoMode) {
          if (videoMode) return true;
          setMaterialVideoError(labelText + '：图片空间仍处于“图片”筛选，无法显示 mp4 视频');
          if (Toast) Toast.show('图片空间没有切换到“视频”类型', 'warning', 5000);
          return closeAfterMaterialVideoFailure(delay);
        }).then(function (videoMode) {
          if (!videoMode) return false;
          return navigateMaterialPathInDialog(modal, materialPath, delay);
        }).then(function (result) {
          if (!result) return false;
          navigationResult = result || navigationResult;
          return selectVideoCardInDialog(modal, videoItem, delay);
        }).then(function (selected) {
          if (!selected) {
            if (lastMaterialVideoError) return false;
            var missingFolders = navigationResult.missing && navigationResult.missing.length
              ? '；未定位到目录：' + navigationResult.missing.join('/')
              : '';
            setMaterialVideoError(labelText + '：在图片空间“' + materialPath + '”中未选中视频“' + videoName + '”' + missingFolders);
            if (Toast) Toast.show('未选中图片空间里的视频：' + videoName, 'warning', 5000);
            return closeAfterMaterialVideoFailure(delay);
          }
          return confirmMaterialVideoDialog(delay).then(function (confirmed) {
            if (!confirmed) {
              setMaterialVideoError(labelText + '：已勾选“' + videoName + '”，但图片空间弹窗没有确认关闭');
              return closeAfterMaterialVideoFailure(delay);
            }
            var areaFinder = isMainVideo
              ? findStrictMainImageArea
              : function () { return findUploadAreaNearText(labels); };
            return waitForVideoUploadComplete(labels, delay, areaFinder, {
              requireVideo: true,
              maxWait: 45000
            }).then(function (verified) {
              if (!verified) {
                return setMaterialVideoError(labelText + '：已从图片空间确认“' + videoName + '”，但发布页没有出现视频预览');
              }
              return true;
            });
          });
        }).then(function (ok) {
          if (Toast) Toast.show(ok ? '图片空间' + labelText + '已选择' : '图片空间' + labelText + '未确认，请检查页面', ok ? 'success' : 'warning', 4000);
          return !!ok;
        });
      });
  }

  function selectMainVideoFromMaterial(videoItem, options) {
    return selectVideoFromMaterial(videoItem, ['商品视频'], options);
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

  function findFileInputNearText(labels, mediaType) {
    labels = Array.isArray(labels) ? labels : [labels];
    mediaType = mediaType || '';
    var inputs = Array.prototype.slice.call(document.querySelectorAll('input[type="file"]'));
    var candidates = inputs.filter(function (input) {
      var accept = (input.getAttribute('accept') || '').toLowerCase();
      if (mediaType === 'video') {
        return !accept || accept.includes('video') || accept.includes('mp4') || accept.includes('mov') || accept.includes('webm');
      }
      return !accept || accept.includes('image') || accept.includes('jpg') || accept.includes('jpeg') || accept.includes('png');
    });
    if (candidates.length === 0) return null;

    function visibleBox(el) {
      var current = el;
      for (var depth = 0; current && depth < 8; depth++, current = current.parentElement) {
        var style = window.getComputedStyle(current);
        var rect = current.getBoundingClientRect();
        if (style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 20 && rect.height > 20) return rect;
      }
      return el.getBoundingClientRect();
    }

    function visible(el) {
      var style = window.getComputedStyle(el);
      var rect = el.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
    }

    function findLabelRect() {
      var best = null;
      var all = Array.prototype.slice.call(document.querySelectorAll('label, span, div, p, section'));
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (!visible(el)) continue;
        var text = (el.innerText || el.textContent || '').replace(/\s+/g, '');
        if (!text) continue;
        var matched = false;
        for (var li = 0; li < labels.length; li++) {
          if (text.indexOf(String(labels[li]).replace(/\s+/g, '')) >= 0) {
            matched = true;
            break;
          }
        }
        if (!matched) continue;
        var rect = el.getBoundingClientRect();
        var score = text.length + rect.width / 100 + rect.height / 100;
        if (!best || score < best.score) best = { rect: rect, score: score, text: text };
      }
      return best && best.rect;
    }

    var labelRect = findLabelRect();

    function labelScore(input, index) {
      var text = '';
      var current = input;
      for (var depth = 0; current && depth < 12; depth++, current = current.parentElement) {
        text += ' ' + (current.innerText || current.textContent || '');
      }
      var score = index;
      for (var li = 0; li < labels.length; li++) {
        if (text.includes(labels[li])) score -= 1000 + labels[li].length;
      }
      if (mediaType === 'video') {
        if (labels.indexOf('商品视频') >= 0 && text.includes('商品讲解视频')) score += 1200;
        if (labels.indexOf('商品讲解视频') >= 0 && text.includes('商品视频') && !text.includes('商品讲解视频')) score += 800;
        if (text.includes('商品主图') || text.includes('详情图') || text.includes('规格图') || text.includes('SKU')) score += 2000;
      }
      var rect = visibleBox(input);
      if (labelRect) {
        var verticalDistance = 0;
        if (rect.top < labelRect.top) verticalDistance = labelRect.top - rect.top;
        else if (rect.top > labelRect.bottom) verticalDistance = rect.top - labelRect.bottom;
        var horizontalDistance = Math.abs(rect.left - labelRect.left);
        score += verticalDistance + horizontalDistance / 10;
        if (rect.top >= labelRect.top - 20 && rect.top <= labelRect.bottom + 220) score -= 500;
      }
      score += Math.max(0, rect.top);
      return score;
    }

    return candidates.map(function (input, index) {
      return { input: input, score: labelScore(input, index) };
    }).sort(function (a, b) {
      return a.score - b.score;
    })[0].input;
  }

  function findUploadAreaNearText(labels) {
    labels = Array.isArray(labels) ? labels : [labels];
    var all = Array.prototype.slice.call(document.querySelectorAll('section, div, form, fieldset'));
    var best = null;
    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      var text = (el.innerText || el.textContent || '').replace(/\s+/g, '');
      if (!text) continue;
      var matched = false;
      for (var li = 0; li < labels.length; li++) {
        if (text.indexOf(String(labels[li]).replace(/\s+/g, '')) >= 0) {
          matched = true;
          break;
        }
      }
      if (!matched) continue;
      var rect = el.getBoundingClientRect();
      if (rect.width <= 20 || rect.height <= 20) continue;
      var score = text.length + rect.height + rect.width / 100;
      if (!best || score < best.score) best = { el: el, score: score };
    }
    return best && best.el;
  }

  function waitForVideoUploadComplete(labels, delay, areaFinder, options) {
    options = options || {};
    var detectedArea = areaFinder ? areaFinder() : findUploadAreaNearText(labels);
    if (options.requireVideo === true && !detectedArea) return Promise.resolve(false);
    var area = detectedArea || document.body;
    var start = Date.now();
    var maxWait = options.maxWait || 45000;
    var requireVideo = options.requireVideo === true;
    var interval = 1500;

    return new Promise(function (resolve) {
      function check() {
        var elapsed = Date.now() - start;
        if (areaFinder) area = areaFinder() || area || document.body;
        var text = area.innerText || area.textContent || '';
        var hasFailure = /上传失败|重新上传|上传错误|失败/.test(text);
        var hasLoading = !!(
          area.querySelector('[class*="uploading"], [class*="progress"], [class*="loading"], [class*="Spn_spinning"]')
        );
        var hasVideo = !!(
          area.querySelector('video') ||
          area.querySelector('[style*=".mp4"], [style*=".mov"], [style*=".webm"]') ||
          /更换视频|删除视频|预览|已上传/.test(text)
        );

        if (hasVideo && !hasFailure) {
          resolve(true);
          return;
        }
        if (hasFailure) {
          resolve(false);
          return;
        }
        if (!requireVideo && !hasLoading && elapsed > 12000) {
          resolve(true);
          return;
        }
        if (elapsed >= maxWait) {
          resolve(false);
          return;
        }
        setTimeout(check, interval);
      }
      setTimeout(check, interval);
    });
  }

  function videoExtensionFrom(url, mimeType) {
    var path = '';
    try {
      path = new URL(url).pathname;
    } catch (e) {
      path = String(url || '');
    }
    var match = path.match(/\.([a-z0-9]+)$/i);
    if (match) return match[1].toLowerCase();
    if ((mimeType || '').includes('webm')) return 'webm';
    if ((mimeType || '').includes('quicktime')) return 'mov';
    return 'mp4';
  }

  function chooseRecordedVideoMimeType() {
    if (typeof MediaRecorder === 'undefined' || !MediaRecorder.isTypeSupported) return '';
    var types = [
      'video/mp4;codecs="avc1.42E01E"',
      'video/mp4',
      'video/webm;codecs=vp9',
      'video/webm;codecs=vp8',
      'video/webm'
    ];
    for (var i = 0; i < types.length; i++) {
      if (MediaRecorder.isTypeSupported(types[i])) return types[i];
    }
    return '';
  }

  function extensionFromVideoMime(mimeType) {
    return (mimeType || '').includes('mp4') ? 'mp4' : 'webm';
  }

  function generateVideoFromImageBlob(imageBlob, options) {
    options = options || {};
    var durationMs = options.durationMs || 4500;
    var targetWidth = options.width || options.size || 960;
    var targetHeight = options.height || options.size || 960;
    var mimeType = chooseRecordedVideoMimeType();
    if (!mimeType) return Promise.reject(new Error('当前浏览器不支持从主图生成视频'));

    return createImageBitmap(imageBlob).then(function (bitmap) {
      return new Promise(function (resolve, reject) {
        var canvas = document.createElement('canvas');
        canvas.width = targetWidth;
        canvas.height = targetHeight;
        var ctx = canvas.getContext('2d');

        function drawFrame() {
          ctx.fillStyle = '#ffffff';
          ctx.fillRect(0, 0, targetWidth, targetHeight);
          var scale = Math.min(targetWidth / bitmap.width, targetHeight / bitmap.height);
          var width = Math.round(bitmap.width * scale);
          var height = Math.round(bitmap.height * scale);
          var x = Math.round((targetWidth - width) / 2);
          var y = Math.round((targetHeight - height) / 2);
          ctx.drawImage(bitmap, x, y, width, height);
        }

        drawFrame();
        var stream = canvas.captureStream(12);
        var chunks = [];
        var recorder;
        try {
          recorder = new MediaRecorder(stream, { mimeType: mimeType });
        } catch (err) {
          reject(err);
          return;
        }
        recorder.ondataavailable = function (event) {
          if (event.data && event.data.size > 0) chunks.push(event.data);
        };
        recorder.onerror = function (event) {
          reject((event && event.error) || new Error('主图视频生成失败'));
        };
        recorder.onstop = function () {
          stream.getTracks().forEach(function (track) { track.stop(); });
          if (bitmap.close) bitmap.close();
          resolve({
            blob: new Blob(chunks, { type: mimeType }),
            mimeType: mimeType,
            extension: extensionFromVideoMime(mimeType)
          });
        };
        recorder.start(500);
        var drawTimer = setInterval(drawFrame, 250);
        setTimeout(function () {
          clearInterval(drawTimer);
          if (recorder.state !== 'inactive') recorder.stop();
        }, durationMs);
      });
    });
  }

  function uploadVideo(videoItem, labels, options) {
    options = options || {};
    var Toast = options.Toast;
    var delay = options.delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };
    var labelText = Array.isArray(labels) ? labels[0] : String(labels || '视频');
    var rawUrl = typeof videoItem === 'string' ? videoItem : videoItem && videoItem.url;
    if (!rawUrl) {
      if (Toast) Toast.show(labelText + '视频数据为空，跳过上传', 'warning', 3000);
      return Promise.resolve(false);
    }

    var url = cleanImageUrl(rawUrl);
    var prepareInput = options.prepareInput ? options.prepareInput(options) : Promise.resolve();

    return prepareInput.then(function () {
      var fileInput = options.fileInputFinder ? options.fileInputFinder() : findFileInputNearText(labels, 'video');
      if (!fileInput) {
        if (Toast) Toast.show('未找到' + labelText + '上传入口', 'warning', 4000);
        console.warn('[PDD填充插件] 未找到' + labelText + ' file input');
        return false;
      }

      if (Toast) Toast.show('正在获取' + labelText + '...', 'info', 3000);
      return fetchImageDirect(url).then(function (result) {
      if (!result) {
        if (Toast) Toast.show(labelText + '获取失败', 'warning', 4000);
        console.warn('[PDD填充插件] ' + labelText + '获取失败: ' + url);
        return false;
      }

      var sourceIsImage = (result.mimeType || '').indexOf('image/') === 0 || !!(videoItem && videoItem.makeVideoFromImage);
      var sourcePromise;
      if (sourceIsImage) {
        if (Toast) Toast.show('正在用主图生成' + labelText + '...', 'info', 4000);
        var isExplainVideo = labels.indexOf('商品讲解视频') >= 0 || labelText.indexOf('讲解') >= 0;
        sourcePromise = generateVideoFromImageBlob(result.blob, isExplainVideo ? {
          width: 720,
          height: 1280,
          durationMs: 12000
        } : {
          width: 960,
          height: 960,
          durationMs: 6000
        }).then(function (generated) {
          return {
            blob: generated.blob,
            mimeType: generated.mimeType,
            ext: generated.extension
          };
        });
      } else {
        var mimeType = result.mimeType || 'video/mp4';
        if (!mimeType.includes('video')) mimeType = 'video/mp4';
        sourcePromise = Promise.resolve({
          blob: result.blob,
          mimeType: mimeType,
          ext: videoExtensionFrom(url, mimeType)
        });
      }

      return sourcePromise.then(function (source) {
        var defaultName = labelText.replace(/\s+/g, '') + '.' + source.ext;
        var fileName = (typeof videoItem === 'object' && videoItem.name) || defaultName;
        fileName = fileName.replace(/\.(jpg|jpeg|png|webp|mp4|mov|webm|m4v)$/i, '.' + source.ext);
        var file = new File([source.blob], fileName, { type: source.mimeType });
        var dataTransfer = new DataTransfer();
        dataTransfer.items.add(file);
        fileInput.files = dataTransfer.files;
        fileInput.dispatchEvent(new Event('change', { bubbles: true }));
        fileInput.dispatchEvent(new Event('input', { bubbles: true }));
        console.log('[PDD填充插件] 已触发' + labelText + '上传: ' + fileName + ', ' + (file.size / 1024 / 1024).toFixed(2) + 'MB, type=' + source.mimeType);
        if (Toast) Toast.show(labelText + '上传中...', 'info', 6000);
        return waitForVideoUploadComplete(labels, delay, options.areaFinder).then(function (ok) {
          if (ok) {
            if (Toast) Toast.show(labelText + '上传完成', 'success', 4000);
          } else {
            if (Toast) Toast.show(labelText + '上传未确认，请检查页面', 'warning', 5000);
          }
          return ok;
        });
      });
      });
    });
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

    var fileInput = options.fileInputFinder ? options.fileInputFinder() : findImageFileInput();
    if (!fileInput) {
      if (Toast) Toast.show('未找到图片上传入口', 'error');
      console.error('[PDD填充插件] 未找到 file input 元素');
      return Promise.resolve(false);
    }
    console.log('[PDD填充插件] 找到 file input:', fileInput, 'accept:', fileInput.accept);

    var self = this;
    var files = [];
    var skippedCount = 0;

    function processImage(index) {
      if (index >= imageItems.length) {
        if (files.length === 0) {
          if (Toast) Toast.show('没有符合要求的图片可上传', 'error');
          return Promise.resolve(false);
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

        return waitForImageUploadComplete(files.length, delay, Toast, options.areaFinder).then(function (uploadOk) {
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
          return uploadOk;
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
    findPrefillMainImageFileInput: findPrefillMainImageFileInput,
    findPrefillMainImageArea: findPrefillMainImageArea,
    activatePrefillMainImageUpload: activatePrefillMainImageUpload,
    findMainVideoFileInput: findMainVideoFileInput,
    activateMainVideoUploadTab: activateMainVideoUploadTab,
    selectVideoFromMaterial: selectVideoFromMaterial,
    selectMainVideoFromMaterial: selectMainVideoFromMaterial,
    getLastMaterialVideoError: getLastMaterialVideoError,
    findDetailImageFileInput: findDetailImageFileInput,
    findFileInputNearText: findFileInputNearText,
    uploadVideo: uploadVideo,
    findSkuImageFileInput: findSkuImageFileInput,
    uploadImages: uploadImages,
    uploadDetailImages: uploadDetailImages,
    uploadSkuImages: uploadSkuImages
  };
}));
