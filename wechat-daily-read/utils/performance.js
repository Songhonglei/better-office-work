/**
 * 性能优化工具函数
 * 提供防抖、节流等性能优化方法
 */

/**
 * 防抖函数
 * 在事件被触发n秒后再执行回调，如果在这n秒内又被触发，则重新计时
 * @param {Function} func - 需要防抖的函数
 * @param {Number} wait - 等待时间（毫秒）
 * @param {Boolean} immediate - 是否立即执行
 * @returns {Function}
 */
function debounce(func, wait = 300, immediate = false) {
  let timeout;

  return function executedFunction(...args) {
    const context = this;

    const later = function() {
      timeout = null;
      if (!immediate) func.apply(context, args);
    };

    const callNow = immediate && !timeout;

    clearTimeout(timeout);
    timeout = setTimeout(later, wait);

    if (callNow) func.apply(context, args);
  };
}

/**
 * 节流函数
 * 规定在一个单位时间内，只能触发一次函数。如果这个单位时间内触发多次函数，只有一次生效
 * @param {Function} func - 需要节流的函数
 * @param {Number} limit - 时间限制（毫秒）
 * @returns {Function}
 */
function throttle(func, limit = 300) {
  let inThrottle;

  return function executedFunction(...args) {
    const context = this;

    if (!inThrottle) {
      func.apply(context, args);
      inThrottle = true;

      setTimeout(() => {
        inThrottle = false;
      }, limit);
    }
  };
}

/**
 * 节流防抖组合
 * 在wait时间内最多执行一次，并在最后一次触发后delay时间后再执行一次
 * @param {Function} func - 需要优化的函数
 * @param {Number} wait - 节流等待时间
 * @param {Number} delay - 防抖延迟时间
 * @returns {Function}
 */
function throttleDebounce(func, wait = 300, delay = 1000) {
  let timeout;
  let throttleTimeout;

  return function executedFunction(...args) {
    const context = this;

    // 防抖部分
    clearTimeout(timeout);
    timeout = setTimeout(() => {
      func.apply(context, args);
    }, delay);

    // 节流部分
    if (!throttleTimeout) {
      func.apply(context, args);
      throttleTimeout = setTimeout(() => {
        throttleTimeout = null;
      }, wait);
    }
  };
}

/**
 * requestAnimationFrame 节流
 * 利用 RAF 实现平滑的滚动监听
 * @param {Function} func - 需要优化的函数
 * @returns {Function}
 */
function rafThrottle(func) {
  let rafId = null;

  return function executedFunction(...args) {
    const context = this;

    if (rafId !== null) {
      return;
    }

    rafId = requestAnimationFrame(() => {
      func.apply(context, args);
      rafId = null;
    });
  };
}

module.exports = {
  debounce,
  throttle,
  throttleDebounce,
  rafThrottle
};
