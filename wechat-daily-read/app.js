const { envId } = require('./config/cloud');

App({
  onLaunch() {
    if (envId && wx.cloud) {
      wx.cloud.init({ env: envId });
    }

    // 检查更新
    this.checkUpdate();
  },

  onShow() {
    console.log('App Show');
  },

  onHide() {
    console.log('App Hide');
  },

  checkUpdate() {
    if (!wx.getUpdateManager) return;
    const updateManager = wx.getUpdateManager();

    updateManager.onCheckForUpdate((res) => {
      console.log('是否有新版本:', res.hasUpdate);
    });

    updateManager.onUpdateReady(() => {
      wx.showModal({
        title: '更新提示',
        content: '新版本已经准备好，是否重启应用？',
        success(res) {
          if (res.confirm) {
            updateManager.applyUpdate();
          }
        }
      });
    });

    updateManager.onUpdateFailed(() => {
      wx.showToast({
        title: '更新失败',
        icon: 'none'
      });
    });
  },

  globalData: {
    userInfo: null,
    hasLogin: false
  }
});