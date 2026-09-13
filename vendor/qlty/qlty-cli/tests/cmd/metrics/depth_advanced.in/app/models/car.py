class Car:
    def __init__(self, make, model, year, color, mileage=0):
        self.make = make
        self.model = model
        self.year = year
        self.color = color
        self.mileage = mileage

    def drive(self, miles):
        if miles > 0:
            self.mileage += miles
        else:
            print("Miles driven must be positive.")

    def paint(self, new_color):
        self.color = new_color

    def __str__(self):
        return f"{self.year} {self.make} {self.model} - {self.color} with {self.mileage} miles"
