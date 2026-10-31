import { useState } from 'react'
import { Button, Input } from 'antd'
import { SendOutlined } from '@ant-design/icons'

interface Props {
  disabled?: boolean
  onSend: (text: string) => void
}

export default function InputBox({ disabled, onSend }: Props) {
  const [text, setText] = useState('')

  const submit = () => {
    const value = text.trim()
    if (!value || disabled) return
    setText('')
    onSend(value)
  }

  return (
    <div className="chat-input">
      <div className="composer-head">
        <span className="composer-label">MESSAGE / 受理记录</span>
        <span className="composer-hint">Enter 提交 · Shift + Enter 换行</span>
      </div>

      <div className="composer-row">
        <Input.TextArea
          value={text}
          onChange={(event) => setText(event.target.value)}
          autoSize={{ minRows: 1, maxRows: 4 }}
          placeholder="输入订单号或问题,例如:查订单 ORDER20260401001"
          onPressEnter={(event) => {
            if (!event.shiftKey) {
              event.preventDefault()
              submit()
            }
          }}
        />
        <Button
          type="primary"
          className="send-button"
          aria-label="提交"
          icon={<SendOutlined />}
          onClick={submit}
          disabled={disabled || !text.trim()}
        >
          提交
        </Button>
      </div>
    </div>
  )
}
