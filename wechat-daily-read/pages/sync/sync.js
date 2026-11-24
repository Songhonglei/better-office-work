const apiService = require('../../utils/api');

Page({
  data: {
    pendingAccounts: [],
    isSyncing: false
  },

  onLoad(options) {
    // 检查是否有从H5页面传来的数据
    if (options.data) {
      try {
        const accounts = JSON.parse(decodeURIComponent(options.data));
        this.setData({
          pendingAccounts: Array.isArray(accounts) ? accounts.slice(0, 100) : []
        });
      } catch (error) {
        console.error('解析数据失败:', error);
      }
    }

    // 检查本地存储的账号
    this.checkLocalAccounts();
  },

  async checkLocalAccounts() {
    try {
      const stored = wx.getStorageSync('pendingAccounts');
      if (Array.isArray(stored)) {
        const additions = stored.filter(account => account && account.biz &&
          !this.data.pendingAccounts.some(current => current.biz === account.biz));
        this.setData({ pendingAccounts: [...this.data.pendingAccounts, ...additions].slice(0, 100) });
      }
    } catch (error) {
      console.error('检查本地账号失败:', error);
    }
  },

  async syncAccounts() {
    if (this.data.pendingAccounts.length === 0) {
      wx.showToast({
        title: '没有待同步的公众号',
        icon: 'none'
      });
      return;
    }

    this.setData({ isSyncing: true });
    wx.showLoading({ title: '同步中...' });

    try {
      let successCount = 0;
      let skipCount = 0;

      for (const account of this.data.pendingAccounts) {
        try {
          if (!account || typeof account.biz !== 'string') continue;
          const result = await apiService.addAccount({
            biz: account.biz,
            name: account.accountName || account.name || '未知公众号',
            category: this.detectCategory(account.name || ''),
          });
          if (!result.success) throw new Error(result.error);
          if (result.isNew) successCount++;
          else skipCount++;
        } catch (error) {
          console.error('同步账号失败:', error);
        }
      }

      wx.hideLoading();
      wx.showModal({
        title: '同步完成',
        content: `成功添加 ${successCount} 个公众号，跳过 ${skipCount} 个重复的`,
        showCancel: false,
        success: () => {
          wx.navigateTo({
            url: '/pages/manage/manage'
          });
        }
      });

      // 清空待同步列表
      this.setData({
        pendingAccounts: [],
        isSyncing: false
      });

    } catch (error) {
      wx.hideLoading();
      wx.showToast({
        title: '同步失败',
        icon: 'none'
      });
      this.setData({ isSyncing: false });
    }
  },

  detectCategory(text) {
    const keywords = {
      '科技': ['科技', '技术', '互联网', 'AI', '人工智能'],
      '财经': ['财经', '经济', '投资', '股票', '基金'],
      '生活': ['生活', '健康', '美食', '旅游', '时尚'],
      '新闻': ['新闻', '资讯', '时事', '热点', '头条'],
      '娱乐': ['娱乐', '影视', '音乐', '游戏', '明星']
    };

    for (const [category, kw] of Object.entries(keywords)) {
      if (kw.some(k => text.includes(k))) {
        return category;
      }
    }
    return '其他';
  },

  removeAccount(e) {
    const { index } = e.currentTarget.dataset;
    const accounts = [...this.data.pendingAccounts];
    accounts.splice(index, 1);
    this.setData({ pendingAccounts: accounts });
  },

  shareSync() {
    wx.showShareMenu({
      withShareTicket: true
    });
  },

  onShareAppMessage() {
    return {
      title: '公众号汇总助手',
      path: '/pages/index/index',
      imageUrl: '/images/share.png'
    };
  }
});