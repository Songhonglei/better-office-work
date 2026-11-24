const apiService = require('../../utils/api');
const { wechatArticleUrl } = require('../../utils/wechat-url');

Page({
  data: {
    inputText: '',
    importResults: [],
    isImporting: false,
    history: []
  },

  onLoad() {
    this.loadImportHistory();
  },

  // 加载导入历史
  async loadImportHistory() {
    this.setData({ history: wx.getStorageSync('importHistory') || [] });
  },

  // 解析输入的文本
  parseUrls() {
    const text = this.data.inputText;
    if (!text.trim()) {
      wx.showToast({
        title: '请输入链接',
        icon: 'none'
      });
      return [];
    }

    // 使用正则表达式提取所有链接
    const urlRegex = /https?:\/\/[^\s]+/g;
    const urls = text.match(urlRegex) || [];

    // 过滤出微信公众号链接
    const wechatUrls = urls.map(url => wechatArticleUrl(url.replace(/[。！？），；,]+$/, ''))).filter(Boolean);

    if (wechatUrls.length === 0) {
      wx.showToast({
        title: '未检测到有效链接',
        icon: 'none'
      });
      return [];
    }

    // 去重
    const uniqueUrls = [...new Set(wechatUrls)];

    wx.showModal({
      title: '检测到链接',
      content: `找到 ${uniqueUrls.length} 个有效的公众号链接，是否开始导入？`,
      success: (res) => {
        if (res.confirm) {
          this.startImport(uniqueUrls);
        }
      }
    });

    return uniqueUrls;
  },

  // 开始批量导入
  async startImport(urls) {
    this.setData({ isImporting: true });
    wx.showLoading({ title: '导入中...' });

    const results = [];
    let successCount = 0;
    let skipCount = 0;
    let failCount = 0;

    for (let i = 0; i < urls.length; i++) {
      const url = urls[i];

      try {
        const res = await apiService.request({ name: 'detectAccount', data: { url } });

        const result = {
          url: url,
          success: res.success,
          message: res.success ?
            (res.isNew ? '添加成功' : '已存在') :
            res.error,
          accountName: res.account?.name || '未知',
          isNew: res.isNew
        };

        results.push(result);

        if (res.success) {
          if (res.isNew) {
            successCount++;
          } else {
            skipCount++;
          }
        } else {
          failCount++;
        }

        // 更新进度
        wx.showLoading({
          title: `导入中 ${i + 1}/${urls.length}`
        });

      } catch (error) {
        results.push({
          url: url,
          success: false,
          message: '请求失败',
          accountName: '未知'
        });
        failCount++;
      }
    }

    wx.hideLoading();
    const history = [...results, ...this.data.history].slice(0, 100);
    wx.setStorageSync('importHistory', history);
    this.setData({
      history,
      importResults: results,
      isImporting: false
    });

    // 显示结果
    wx.showModal({
      title: '导入完成',
      content: `成功: ${successCount}, 跳过: ${skipCount}, 失败: ${failCount}`,
      showCancel: false
    });
  },

  // 清空输入
  clearInput() {
    this.setData({
      inputText: '',
      importResults: []
    });
  },

  // 分享导入结果
  onShareAppMessage() {
    const successCount = this.data.importResults.filter(r => r.success).length;
    return {
      title: `成功导入 ${successCount} 个公众号`,
      path: '/pages/batch-import/batch-import',
      imageUrl: '/images/share.png'
    };
  }
});