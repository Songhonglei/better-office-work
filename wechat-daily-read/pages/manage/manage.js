const apiService = require('../../utils/api');
const testConfig = require('../../config/test');
const { debounce } = require('../../utils/performance');

Page({
  data: {
    accounts: [],
    loading: true,
    pageReady: false,
    showAddPopup: false,
    showAddMenu: false,
    showGuide: false,
    showClipboardTip: false,
    clipboardAnimating: false,
    clipboardUrl: '',
    addActions: [
      { name: '手动添加', subname: '填写公众号信息', icon: 'plus' },
      { name: '智能粘贴', subname: '从剪贴板识别链接', icon: 'scan' },
      { name: '批量导入', subname: '导入多个公众号', icon: 'orders-o' }
    ],
    newAccount: {
      name: '',
      biz: '',
      category: ''
    },
    categories: ['科技', '财经', '生活', '娱乐', '教育', '其他'],
    testMode: testConfig.isTestMode
  },

  onLoad() {
    this.loadAccounts();
    // 检查是否首次访问
    this.checkFirstVisit();
  },

  onShow() {
    this.loadAccounts();
    // 检查剪贴板是否有公众号链接（防抖优化）
    clearTimeout(this.checkClipboardTimer);
    this.checkClipboardTimer = setTimeout(() => {
      this.checkClipboard();
    }, 500);
  },

  onReady() {
    // 页面渲染完成后触发列表动画
    setTimeout(() => {
      this.setData({ pageReady: true });
    }, 100);
  },

  async loadAccounts() {
    this.setData({ loading: true });

    try {
      const res = await apiService.getAccounts();

      if (res.success) {
        this.setData({
          accounts: res.data || [],
          loading: false
        });
      } else {
        this.setData({ loading: false });
        wx.showToast({
          title: res.error || '获取数据失败',
          icon: 'none'
        });
      }
    } catch (error) {
      console.error('获取账号列表失败:', error);
      this.setData({ loading: false });
      wx.showToast({
        title: '获取数据失败',
        icon: 'none'
      });
    }
  },

  // 显示添加菜单
  showAddMenu() {
    this.setData({ showAddMenu: true });
  },

  // 关闭添加菜单
  onCloseAddMenu() {
    this.setData({ showAddMenu: false });
    console.log('关闭添加菜单');
  },

  // 处理菜单项选择
  handleMenuSelect(e) {
    const { action } = e.currentTarget.dataset;

    if (!action || !action.name) {
      console.error('无法获取action对象:', e);
      return;
    }

    // 首先关闭菜单
    this.setData({ showAddMenu: false });

    // 延迟处理，确保菜单关闭动画完成
    setTimeout(() => {
      if (action.name === '手动添加') {
        // 手动添加 - 打开表单填写
        this.showAddAccount();
      } else if (action.name === '智能粘贴') {
        // 智能粘贴 - 打开输入框让用户粘贴链接
        this.openClipboardInput();
      } else if (action.name === '批量导入') {
        // 批量导入
        this.goToBatchImport();
      }
    }, 300);
  },

  // 选择添加方式 (备用)
  onSelectAddAction(e) {
    // Vant action-sheet 返回的是整个action对象，包含name、subname、icon
    const action = e.detail;

    if (!action) {
      console.error('无法获取action对象:', e);
      return;
    }

    this.setData({ showAddMenu: false });

    // 根据action的name来判断用户选择了哪个选项
    if (action.name === '手动添加') {
      // 手动添加 - 打开表单填写
      this.showAddAccount();
    } else if (action.name === '智能粘贴') {
      // 智能粘贴 - 打开输入框让用户粘贴链接
      this.openClipboardInput();
    } else if (action.name === '批量导入') {
      // 批量导入
      this.goToBatchImport();
    }
  },

  // 打开剪贴板输入框
  openClipboardInput() {
    wx.showModal({
      title: '粘贴公众号文章链接',
      editable: true,
      placeholderText: '支持直接粘贴文章链接',
      success: (res) => {
        if (res.confirm && res.content) {
          // 用户输入了链接
          this.addFromClipboard(res.content);
        }
      }
    });
  },

  showAddAccount() {
    this.setData({
      showAddPopup: true,
      newAccount: {
        name: '',
        biz: '',
        category: this.data.categories[0]
      }
    });
  },

  hideAddAccount() {
    this.setData({
      showAddPopup: false
    });
  },

  onNameChange(e) {
    this.setData({
      'newAccount.name': e.detail.value
    });
  },

  onBizChange(e) {
    this.setData({
      'newAccount.biz': e.detail.value
    });
  },

  onCategoryChange(e) {
    const index = e.detail.value;
    this.setData({
      'newAccount.category': this.data.categories[index]
    });
  },

  async addAccount() {
    const { name, biz, category } = this.data.newAccount;

    if (!name || !biz) {
      wx.showToast({
        title: '请填写完整信息',
        icon: 'none'
      });
      return;
    }

    wx.showLoading({ title: '添加中...' });

    try {
      const result = await apiService.addAccount({ name: name.trim(), biz: biz.trim(), category });
      if (!result.success) throw new Error(result.error);

      wx.showToast({
        title: '添加成功',
        icon: 'success'
      });

      this.hideAddAccount();
      this.loadAccounts();
    } catch (error) {
      console.error('添加账号失败:', error);
      wx.showToast({
        title: '添加失败',
        icon: 'none'
      });
    } finally {
      wx.hideLoading();
    }
  },

  async toggleAccount(e) {
    const { id, isActive } = e.currentTarget.dataset;

    try {
      const result = await apiService.toggleAccount(id, !isActive);
      if (!result.success) throw new Error(result.error);

      this.loadAccounts();
    } catch (error) {
      console.error('更新账号失败:', error);
      wx.showToast({
        title: '操作失败',
        icon: 'none'
      });
    }
  },

  async deleteAccount(e) {
    const { id } = e.currentTarget.dataset;

    wx.showModal({
      title: '提示',
      content: '确定要删除这个公众号吗？',
      success: async (res) => {
        if (res.confirm) {
          try {
            const result = await apiService.deleteAccount(id);
            if (!result.success) throw new Error(result.error);

            wx.showToast({
              title: '删除成功',
              icon: 'success'
            });

            this.loadAccounts();
          } catch (error) {
            console.error('删除账号失败:', error);
            wx.showToast({
              title: '删除失败',
              icon: 'none'
            });
          }
        }
      }
    });
  },

  // 检查剪贴板
  async checkClipboard() {
    try {
      const res = await wx.getClipboardData();
      const url = res.data;

      if (url && url.includes('mp.weixin.qq.com') && url.includes('__biz=')) {
        // 检测到公众号链接，显示浮动卡片
        this.setData({
          clipboardUrl: url,
          showClipboardTip: true,
          clipboardAnimating: true
        });

        // 10秒后自动隐藏
        setTimeout(() => {
          this.dismissClipboard();
        }, 10000);
      }
    } catch (error) {
      console.error('检查剪贴板失败:', error);
    }
  },

  // 忽略剪贴板提示
  dismissClipboard() {
    this.setData({ clipboardAnimating: false });
    setTimeout(() => {
      this.setData({
        showClipboardTip: false,
        clipboardUrl: ''
      });
    }, 300);
  },

  // 接受剪贴板并添加
  acceptClipboard() {
    const url = this.data.clipboardUrl;
    this.dismissClipboard();
    this.addFromClipboard(url);
  },

  // 从剪贴板添加公众号
  async addFromClipboard(url) {
    if (!url) {
      wx.showToast({
        title: '链接不能为空',
        icon: 'none'
      });
      return;
    }

    wx.showLoading({ title: '正在解析...' });

    try {
      // 使用API服务解析公众号信息
      const res = await apiService.request({
        name: 'detectAccount',
        data: {
          url: url,
          openid: wx.getStorageSync('openid') || 'anonymous'
        }
      });

      wx.hideLoading();

      if (res.success) {
        if (res.isNew) {
          wx.showToast({
            title: '添加成功',
            icon: 'success'
          });
        } else {
          wx.showToast({
            title: '公众号已存在',
            icon: 'none'
          });
        }
        this.loadAccounts();
      } else {
        wx.showModal({
          title: '解析失败',
          content: res.error || '无法识别公众号信息，请检查链接',
          confirmText: '重试',
          success: (modalRes) => {
            if (modalRes.confirm) {
              this.openClipboardInput();
            }
          }
        });
      }
    } catch (error) {
      wx.hideLoading();
      wx.showModal({
        title: '添加失败',
        content: error.message || '网络错误，请重试',
        confirmText: '重试',
        success: (res) => {
          if (res.confirm) {
            this.openClipboardInput();
          }
        }
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
          this.addFromClipboard(res.content);
        }
      }
    });
  },

  // 跳转到批量导入
  goToBatchImport() {
    wx.navigateTo({
      url: '/pages/batch-import/batch-import'
    });
  },

  // 检查是否首次访问
  checkFirstVisit() {
    const hasVisited = wx.getStorageSync('has_visited_manage');
    if (!hasVisited) {
      // 延迟显示引导，确保页面加载完成
      setTimeout(() => {
        this.setData({ showGuide: true });
      }, 500);
    }
  },

  // 关闭引导
  closeGuide() {
    this.setData({ showGuide: false });
    // 标记已访问
    wx.setStorageSync('has_visited_manage', true);
  },

  // 阻止事件冒泡
  stopPropagation() {
    // 阻止点击模态框时触发overlay的关闭事件
  }
});