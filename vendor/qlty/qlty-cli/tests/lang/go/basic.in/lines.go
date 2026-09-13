func f1() {
    tempFile, err := ioutil.TempFile("", "go*.go")
	if err != nil {
		fmt.Println("Error creating temporary file:", err)
		return
	}
	defer os.Remove(tempFile.Name())

    bar
}

// Foo
func f2() {
    bar // does not count as comment line
}

// multi-line comment
/*

line1
line2

line4
*/

func f3() {
    bar
}
