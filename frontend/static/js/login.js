(() => {
  const { api, setToken, setStoredUser, getToken } = window.App
  const form = document.getElementById('login-form')
  const alertBox = document.getElementById('login-alert')
  const localMode = document.getElementById('local-mode')

  const rawNext = new URLSearchParams(location.search).get('next') || '/'
  // 只允许站内路径,避免 next 被构造为外部跳转
  const next = rawNext.startsWith('/') && !rawNext.startsWith('//') ? rawNext : '/'

  const showError = (message) => {
    alertBox.textContent = message
    alertBox.style.display = 'block'
  }

  ;(async () => {
    try {
      const config = await api('/auth/config')
      if (!config.auth_enabled) {
        form.style.display = 'none'
        localMode.style.display = 'block'
        return
      }
      if (getToken()) {
        try {
          const user = await api('/auth/me')
          setStoredUser(user)
          location.href = next
          return
        } catch {
          localStorage.removeItem('after_sales_token')
          localStorage.removeItem('after_sales_user')
        }
      }
    } catch (error) {
      showError(error.message)
    }
  })()

  form.addEventListener('submit', async (event) => {
    event.preventDefault()
    alertBox.style.display = 'none'
    const username = document.getElementById('username').value.trim()
    const password = document.getElementById('password').value
    try {
      const result = await api('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      })
      setToken(result.token)
      setStoredUser({
        user_id: result.user_id,
        username: result.username,
        roles: [result.user_type],
      })
      location.href = next
    } catch (error) {
      showError(error.message)
    }
  })

  document.getElementById('local-enter').addEventListener('click', () => {
    location.href = next
  })
})()
