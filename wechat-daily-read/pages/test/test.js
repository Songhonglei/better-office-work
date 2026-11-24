const apiService = require('../../utils/api');
const testConfig = require('../../config/test');

Page({
  data: {
    testMode: testConfig.isTestMode,
    currentScenario: testConfig.currentScenario,
    logs: [],
    testResults: []
  },

  onLoad() {
    // 添加初始日志
    this.addLog('页面加载', `测试模式: ${testConfig.isTestMode ? '开启' : '关闭'}`);
  },

  // 添加日志
  addLog(action, result) {
    const logs = this.data.logs;
    logs.unshift({
      time: new Date().toLocaleTimeString(),
      action: action,
      result: result
    });

    // 保留最新20条
    if (logs.length > 20) {
      logs.pop();
    }

    this.setData({ logs });
  },

  // 切换测试场景
  switchScenario(e) {
    const scenario = e.currentTarget.dataset.scenario;
    testConfig.setScenario(scenario);
    this.setData({
      currentScenario: scenario
    });
    this.addLog('切换场景', `切换到 ${scenario}`);
  },

  // 测试获取文章
  async testGetArticles() {
    this.addLog('测试获取文章', '开始...');

    try {
      const res = await apiService.request({
        name: 'getDailyArticles',
        data: { date: '2025-01-08' }
      });

      this.addLog('获取文章结果', JSON.stringify(res).substring(0, 100) + '...');
      this.setData({
        testResults: res.articles || []
      });
    } catch (error) {
      this.addLog('获取文章失败', error.message);
    }
  },

  // 测试添加公众号
  async testAddAccount() {
    // 测试几种不同的URL
    const testUrls = [
      'https://mp.weixin.qq.com/s?__biz=MzIwNDM0ODU3OA==&mid=123&sn=test', // 正常
      'https://mp.weixin.qq.com/s?mid=123&sn=test', // 缺少biz
      'https://example.com/test', // 非微信链接
      'invalid url' // 无效URL
    ];

    const url = testUrls[Math.floor(Math.random() * testUrls.length)];

    this.addLog('测试添加账号', `URL: ${url.substring(0, 50)}...`);

    try {
      const res = await apiService.request({
        name: 'detectAccount',
        data: { url: url }
      });

      this.addLog('添加账号结果', JSON.stringify(res));
    } catch (error) {
      this.addLog('添加账号失败', error.message);
    }
  },

  // 测试语音合成
  async testTextToSpeech() {
    const testText = '这是一段测试语音合成的文本内容';

    this.addLog('测试语音合成', '开始...');

    try {
      const res = await apiService.request({
        name: 'textToSpeech',
        data: { text: testText }
      });

      this.addLog('语音合成结果', JSON.stringify(res));
    } catch (error) {
      this.addLog('语音合成失败', error.message);
    }
  },

  // 测试生成摘要
  async testGenerateSummary() {
    this.addLog('测试生成摘要', '开始...');

    try {
      const res = await apiService.request({
        name: 'generateSummary',
        data: {
          articles: this.data.testResults.slice(0, 5)
        }
      });

      this.addLog('生成摘要结果', res.summary ? res.summary.substring(0, 100) + '...' : '无摘要');
    } catch (error) {
      this.addLog('生成摘要失败', error.message);
    }
  },

  // 清空日志
  clearLogs() {
    this.setData({ logs: [] });
    this.addLog('清空日志', '日志已清空');
  },

  // 导出测试报告
  exportReport() {
    const report = {
      testTime: new Date().toISOString(),
      scenario: testConfig.currentScenario,
      testMode: testConfig.isTestMode,
      results: this.data.testResults,
      logs: this.data.logs
    };

    wx.setClipboardData({
      data: JSON.stringify(report, null, 2),
      success: () => {
        wx.showToast({
          title: '测试报告已复制',
          icon: 'success'
        });
      }
    });
  },

  // 模拟网络问题
  simulateNetworkIssue() {
    testConfig.errorRate.network = 0.8; // 80%错误率
    this.addLog('模拟网络问题', '网络错误率设置为80%');
  },

  // 恢复正常
  restoreNormal() {
    testConfig.errorRate.network = 0.1;
    testConfig.errorRate.api = 0.05;
    testConfig.setScenario('normal');
    this.setData({
      currentScenario: 'normal'
    });
    this.addLog('恢复正常', '所有设置已重置');
  }
});