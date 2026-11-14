package main

import (
	"errors"
	"syscall"
	"unsafe"
)

var (
	kernel32            = syscall.NewLazyDLL("kernel32.dll")
	createMutex         = kernel32.NewProc("CreateMutexW")
	waitForSingleObject = kernel32.NewProc("WaitForSingleObject")
	releaseMutex        = kernel32.NewProc("ReleaseMutex")
	closeHandle         = kernel32.NewProc("CloseHandle")
)

type mutexHandle uintptr

func acquireMutex(name string) (mutexHandle, error) {
	value, err := syscall.UTF16PtrFromString(name)
	if err != nil {
		return 0, err
	}
	handle, _, callErr := createMutex.Call(0, 0, uintptr(unsafe.Pointer(value)))
	if handle == 0 {
		return 0, callErr
	}
	result, _, _ := waitForSingleObject.Call(handle, 60000)
	if result != 0 && result != 0x80 {
		closeHandle.Call(handle)
		return 0, errors.New("another launcher owns the update transaction")
	}
	return mutexHandle(handle), nil
}

func (m mutexHandle) Close() {
	releaseMutex.Call(uintptr(m))
	closeHandle.Call(uintptr(m))
}
