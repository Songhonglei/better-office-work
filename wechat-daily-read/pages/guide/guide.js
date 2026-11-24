Page({
  data: {
    currentStep: 0,
    steps: [
      {
        title: '第一步：复制公众号链接',
        desc: '在微信中打开任意公众号文章',
        icon: 'https://via.placeholder.com/100x100/4caf50/ffffff?text=1'
      },
      {
        title: '第二步：打开小程序',
        desc: '返回小程序，会自动检测剪贴板',
        icon: 'https://via.placeholder.com/100x100/2196f3/ffffff?text=2'
      },
      {
        title: '第三步：确认添加',
        desc: '点击确定即可添加到汇总列表',
        icon: 'https://via.placeholder.com/100x100/ff9800/ffffff?text=3'
      }
    ],
    showClipboard: false
  },

  onLoad() {
    // 检查是否是首次使用
    const isFirstTime = wx.getStorageSync('is_first_time');
    if (!isFirstTime) {
      wx.setStorageSync('is_first_time', false);
    }
  },

  nextStep() {
    if (this.data.currentStep < this.data.steps.length - 1) {
      this.setData({
        currentStep: this.data.currentStep + 1
      });
    } else {
      // 完成引导，跳转到管理页面
      wx.switchTab({
        url: '/pages/manage/manage'
      });
    }
  },

  prevStep() {
    if (this.data.currentStep > 0) {
      this.setData({
        currentStep: this.data.currentStep - 1
      });
    }
  },

  async tryDemo() {
    // 复制一个示例公众号链接
    const demoUrl = 'https://mp.weixin.qq.com/s?__biz=MzA5NzQ5NDMyOA==&mid=2650936740&idx=1&sn=demo123';

    try {
      await wx.setClipboardData({
        data: demoUrl
      });

      this.setData({ showClipboard: true });
      wx.showToast({
        title: '已复制示例链接',
        icon: 'success'
      });

      setTimeout(() => {
        this.setData({ showClipboard: false });
      }, 2000);
    } catch (error) {
      console.error('复制失败:', error);
    }
  },

  skipGuide() {
    wx.switchTab({
      url: '/pages/manage/manage'
    });
  }
});