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
      <Input.TextArea
        value={text}
        onChange={(event) => setText(event.target.value)}
        autoSize={{ minRows: 1, maxRows: 4 }}
        placeholder="输入您的问题...(Enter 发送,Shift+Enter 换行)"
        onPressEnter={(event) => {
          if (!event.shiftKey) {
            event.preventDefault()
            submit()
          }
        }}
      />
      <Button
        type="primary"
        icon={<SendOutlined />}
        onClick={submit}
        disabled={disabled || !text.trim()}
      >
        发送
      </Button>
    </div>
  )
}
