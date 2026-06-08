// input-handler.js - 输入框处理模块
/**
 * @typedef {import('../types').Control} Control
 * @typedef {import('../types').DelayFunction} DelayFunction
 * @typedef {import('../types').TypeLikeHumanOptions} TypeLikeHumanOptions
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.InputHandler = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var nativeInputValueSetter;
  try {
    nativeInputValueSetter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value'
    ).set;
  } catch (e) {
    nativeInputValueSetter = null;
  }

  /**
   * 模拟人工输入（异步版本，等待完成）
   * @param {HTMLInputElement} input - 输入框元素
   * @param {string} value - 要输入的值
   * @param {number} [delayMs=100] - 每次按键延迟
   * @param {DelayFunction} [delay] - 延迟函数
   * @returns {Promise<void>} 完成时resolve
   */
  function typeLikeHuman(input, value, delayMs, delay) {
    delayMs = delayMs || 100;
    delay = delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };

    input.focus();
    input.dispatchEvent(new Event('focus', { bubbles: true }));

    var tracker = input._valueTracker;
    if (tracker) tracker.setValue('');
    if (nativeInputValueSetter) nativeInputValueSetter.call(input, '');
    input.dispatchEvent(new Event('input', { bubbles: true }));

    return delay(50).then(function () {
      var accumulated = '';
      var chars = value.split('');
      var i = 0;

      function typeNext() {
        if (i >= chars.length) {
          input.dispatchEvent(new Event('change', { bubbles: true }));
          input.dispatchEvent(new Event('blur', { bubbles: true }));
          return Promise.resolve();
        }
        accumulated += chars[i];
        var t = input._valueTracker;
        if (t) t.setValue(accumulated.slice(0, -1));
        if (nativeInputValueSetter) nativeInputValueSetter.call(input, accumulated);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        i++;
        return delay(delayMs).then(typeNext);
      }
      return typeNext();
    });
  }

  /**
   * 设置输入框的值
   * @param {HTMLInputElement} input - 输入框元素
   * @param {string} value - 要设置的值
   */
  function setInputValue(input, value) {
    var tracker = input._valueTracker;
    if (tracker) tracker.setValue('');

    input.focus();
    input.setSelectionRange(0, input.value.length);
    var execOk = document.execCommand('insertText', false, value);

    if (!execOk || input.value !== String(value)) {
      if (nativeInputValueSetter) {
        nativeInputValueSetter.call(input, value);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }
  }

  /**
   * 填充文本输入框
   * @param {Control} control - 包含元素的控制对象
   * @param {string} value - 要填充的值
   * @param {DelayFunction} [delay] - 延迟函数
   * @param {Function} [simulateClick] - 模拟点击函数
   * @returns {Promise<boolean>} 是否填充成功
   */
  function fillTextInput(control, value, delay, simulateClick) {
    var input = control.el;
    if (!input) return Promise.resolve(false);

    delay = delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };

    input.focus();
    input.dispatchEvent(new Event('focus', { bubbles: true }));

    return delay(100).then(function () {
      setInputValue(input, value);
      return delay(100).then(function () {
        input.dispatchEvent(new Event('blur', { bubbles: true }));
        return true;
      });
    });
  }

  /**
   * 同步模拟人工输入（递归版本）
   * @param {HTMLInputElement} input - 输入框元素
   * @param {string} value - 要输入的值
   * @param {number} [delayMs=100] - 每次按键延迟
   * @returns {boolean} 是否开始成功
   */
  function syncTypeLikeHuman(input, value, delayMs) {
    delayMs = delayMs || 100;

    input.focus();
    input.dispatchEvent(new Event('focus', { bubbles: true }));

    var tracker = input._valueTracker;
    if (tracker) tracker.setValue('');
    if (nativeInputValueSetter) nativeInputValueSetter.call(input, '');
    input.dispatchEvent(new Event('input', { bubbles: true }));

    var accumulated = '';
    var chars = value.split('');
    var i = 0;

    function typeNext() {
      if (i >= chars.length) {
        input.dispatchEvent(new Event('change', { bubbles: true }));
        input.dispatchEvent(new Event('blur', { bubbles: true }));
        return false;
      }
      accumulated += chars[i];
      var t = input._valueTracker;
      if (t) t.setValue(accumulated.slice(0, -1));
      if (nativeInputValueSetter) nativeInputValueSetter.call(input, accumulated);
      input.dispatchEvent(new Event('input', { bubbles: true }));
      i++;
      setTimeout(typeNext, delayMs);
      return true;
    }
    typeNext();
  }

  return {
    nativeInputValueSetter: nativeInputValueSetter,
    typeLikeHuman: typeLikeHuman,
    setInputValue: setInputValue,
    fillTextInput: fillTextInput,
    syncTypeLikeHuman: syncTypeLikeHuman
  };
}));