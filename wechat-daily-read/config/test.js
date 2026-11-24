const { envId } = require('./cloud');

// 演示模式配置
const testConfig = {
  // 是否开启测试模式（不调用真实云函数）
  isTestMode: !envId,

  // 模拟网络延迟（毫秒）
  networkDelay: {
    fast: 300,
    normal: 800,
    slow: 2000
  },

  // 模拟错误概率（0-1）
  errorRate: {
    network: 0,  // 10%网络错误概率
    api: 0      // 5% API错误概率
  },

  // 测试场景
  scenarios: {
    normal: 'normal',      // 正常场景
    slow: 'slow',          // 网络慢场景
    error: 'error',        // 错误场景
    empty: 'empty'         // 空数据场景
  },

  // 当前测试场景
  currentScenario: 'normal',

  // 切换测试场景
  setScenario(scenario) {
    if (Object.values(this.scenarios).includes(scenario)) {
      this.currentScenario = scenario;
      console.log(`测试场景切换为: ${scenario}`);
    }
  },

  // 生成随机错误
  generateError() {
    const errors = [
      { message: '网络连接失败，请检查网络设置', code: -1 },
      { message: '服务器繁忙，请稍后重试', code: -2 },
      { message: '请求超时，请重试', code: -3 },
      { message: '数据解析失败', code: -4 },
      { message: '权限不足', code: -5 }
    ];
    return errors[Math.floor(Math.random() * errors.length)];
  },

  // 获取延迟时间
  getDelay() {
    switch (this.currentScenario) {
      case this.scenarios.fast:
        return this.networkDelay.fast;
      case this.scenarios.slow:
        return this.networkDelay.slow;
      default:
        return this.networkDelay.normal;
    }
  }
};

module.exports = testConfig;