// API服务层
const mockData = require('./mock');
const testConfig = require('../config/test');

// API服务类
class ApiService {
  constructor() {
    this.isTestMode = testConfig.isTestMode;
  }

  // 通用请求方法
  async request(options) {
    if (this.isTestMode) {
      return this.mockRequest(options);
    } else {
      return this.realRequest(options);
    }
  }

  // 真实请求（调用云函数）
  async realRequest(options) {
    try {
      if (!wx.cloud) return { success: false, error: '微信云开发不可用' };
      const res = await wx.cloud.callFunction({
        name: options.name,
        data: options.data || {}
      });
      return res.result || { success: false, error: '云函数未返回结果' };
    } catch (error) {
      console.error('API请求失败:', error);
      return {
        success: false,
        error: error.message || '请求失败'
      };
    }
  }

  // Mock请求（使用测试数据）
  async mockRequest(options) {
    const delay = testConfig.getDelay();

    // 模拟网络错误
    if (testConfig.currentScenario === testConfig.scenarios.error) {
      await this.delay(delay);
      return {
        success: false,
        error: '网络连接失败，请检查网络设置'
      };
    }

    // 根据不同的API调用返回相应数据
    switch (options.name) {
      case 'getDailyArticles':
        return await this.getDailyArticles(options.data);

      case 'detectAccount':
        return await this.detectAccount(options.data);

      case 'textToSpeech':
        return await this.textToSpeech(options.data);

      case 'generateSummary':
        return await this.generateSummary(options.data);

      default:
        return {
          success: false,
          error: '未知的API调用'
        };
    }
  }

  // 获取每日文章
  async getDailyArticles(data) {
    const delay = testConfig.getDelay();
    await this.delay(delay);

    if (testConfig.currentScenario === testConfig.scenarios.empty) {
      return {
        success: true,
        articles: [],
        summary: '今日暂无新文章',
        total: 0
      };
    }

    await this.getAccounts();
    return await mockData.getDailyArticles(data.date);
  }

  // 检测/添加公众号
  async detectAccount(data) {
    const delay = testConfig.getDelay();
    await this.delay(delay);

    // 模拟API错误
    if (Math.random() < testConfig.errorRate.api) {
      return {
        success: false,
        error: testConfig.generateError().message
      };
    }

    const result = await mockData.addAccount(data.url);
    if (result.success) {
      wx.setStorageSync('demoAccounts', mockData.accounts);
    }
    return result;
  }

  // 文字转语音
  async textToSpeech() {
    return { success: false, error: '演示模式尚未配置语音服务' };
  }

  // 生成摘要
  async generateSummary(data) {
    const delay = testConfig.getDelay();
    await this.delay(delay);

    const articles = data.articles || mockData.articles;
    const summary = mockData.generateSummary(articles);

    return {
      success: true,
      summary
    };
  }

  async getAccounts() {
    if (!this.isTestMode) return this.realRequest({ name: 'detectAccount', data: { action: 'list' } });
    const saved = wx.getStorageSync('demoAccounts');
    if (Array.isArray(saved)) mockData.accounts = saved;
    return { success: true, data: mockData.accounts };
  }

  async addAccount(account) {
    if (!this.isTestMode) return this.realRequest({ name: 'detectAccount', data: { action: 'add', ...account } });
    await this.getAccounts();
    const existing = mockData.accounts.find(row => row.biz === account.biz);
    if (existing) return { success: true, account: existing, isNew: false };
    const entry = { ...account, _id: String(Date.now()), isActive: true };
    mockData.accounts.push(entry);
    wx.setStorageSync('demoAccounts', mockData.accounts);
    return { success: true, account: entry, isNew: true };
  }

  async toggleAccount(id, isActive) {
    if (!this.isTestMode) return this.realRequest({ name: 'detectAccount', data: { action: 'toggle', id, isActive } });
    await this.getAccounts();
    const row = mockData.accounts.find(item => (item._id || item.id) === id);
    if (!row) return { success: false, error: '公众号不存在' };
    row.isActive = isActive;
    wx.setStorageSync('demoAccounts', mockData.accounts);
    return { success: true };
  }

  async deleteAccount(id) {
    if (!this.isTestMode) return this.realRequest({ name: 'detectAccount', data: { action: 'delete', id } });
    await this.getAccounts();
    mockData.accounts = mockData.accounts.filter(row => (row._id || row.id) !== id);
    wx.setStorageSync('demoAccounts', mockData.accounts);
    return { success: true };
  }

  // 延迟函数
  delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  // 切换测试场景（仅测试模式下有效）
  switchScenario(scenario) {
    if (this.isTestMode) {
      testConfig.setScenario(scenario);
      return true;
    }
    return false;
  }

  // 获取当前测试场景
  getCurrentScenario() {
    return this.isTestMode ? testConfig.currentScenario : 'production';
  }
}

// 创建单例
const apiService = new ApiService();

module.exports = apiService;