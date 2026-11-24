Page({
  data: {
    showGuide: false,
    clipboardUrl: ''
  },

  onLoad() {
    // 检查剪贴板
    this.checkClipboard();
  },

  // 检查剪贴板是否有公众号文章链接
  async checkClipboard() {
    try {
      const res = await wx.getClipboardData();
      const url = res.data;

      if (url && url.includes('mp.weixin.qq.com')) {
        this.setData({
          clipboardUrl: url
        });

        wx.showModal({
          title: '检测到公众号链接',
          content: '是否要添加这个公众号？',
          confirmText: '添加',
          success: (res) => {
            if (res.confirm) {
              this.addFromClipboard();
            }
          }
        });
      }
    } catch (error) {
      console.error('读取剪贴板失败:', error);
    }
  },

  // 从剪贴板添加公众号
  async addFromClipboard() {
    wx.showLoading({ title: '解析中...' });

    try {
      const res = await wx.cloud.callFunction({
        name: 'detectAccount',
        data: {
          url: this.data.clipboardUrl,
          action: 'extract_info'
        }
      });

      if (res.result.success) {
        await this.saveAccount(res.result.accountInfo);
      } else {
        wx.showToast({
          title: '解析失败',
          icon: 'none'
        });
      }
    } catch (error) {
      wx.hideLoading();
      wx.showToast({
        title: '添加失败',
        icon: 'none'
      });
    }
  },

  // 保存账号
  async saveAccount(accountInfo) {
    try {
      const db = wx.cloud.database();

      // 检查是否已存在
      const existRes = await db.collection('accounts')
        .where({ biz: accountInfo.biz })
        .get();

      if (existRes.data.length > 0) {
        wx.hideLoading();
        wx.showToast({
          title: '公众号已存在',
          icon: 'none'
        });
        return;
      }

      // 添加新账号
      await db.collection('accounts').add({
        data: {
          biz: accountInfo.biz,
          name: accountInfo.name,
          category: accountInfo.category || '其他',
          isActive: true,
          autoAdded: true,
          createTime: new Date(),
          sourceUrl: accountInfo.url
        }
      });

      wx.hideLoading();
      wx.showToast({
        title: '添加成功',
        icon: 'success'
      });

    } catch (error) {
      wx.hideLoading();
      wx.showToast({
        title: '保存失败',
        icon: 'none'
      });
    }
  },

  // 手动输入链接
  manualInput() {
    wx.showModal({
      title: '输入公众号文章链接',
      editable: true,
      placeholderText: '粘贴公众号文章链接...',
      success: (res) => {
        if (res.confirm && res.content) {
          this.setData({ clipboardUrl: res.content });
          this.addFromClipboard();
        }
      }
    });
  },

  // 显示使用指南
  showGuide() {
    this.setData({ showGuide: true });
  },

  hideGuide() {
    this.setData({ showGuide: false });
  },

  // 分享给好友
  onShareAppMessage() {
    return {
      title: '公众号汇总助手',
      path: '/pages/share-helper/share-helper',
      imageUrl: '/images/share.png'
    };
  },

  // 生成书签
  generateBookmark() {
    wx.showModal({
      title: '添加书签',
      content: '1. 在浏览器打开: https://your-domain.com/bookmark.html\n2. 添加到书签\n3. 命名为"添加到公众号汇总"',
      showCancel: false
    });
  }
});