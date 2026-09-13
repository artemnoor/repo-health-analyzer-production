type Rectangle struct {
	width  float64
	height float64
}

func NewRectangle() *Rectangle {
	return &Rectangle{
		width:  1,
		height: 2,
	}
}

func (r *Rectangle) Area() float64 {
	return r.width * r.height
}

func (r *Rectangle) Foo() {
}

func (r *Rectangle) Bar() {
}
