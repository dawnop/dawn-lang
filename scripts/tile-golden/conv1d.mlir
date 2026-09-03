cuda_tile.module @m {
  entry @conv1d(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<128xi32>
    %8 = iota : tile<128xi32>
    %9 = addi %7, %8 : tile<128xi32>
    %10 = constant <i32: 996> : tile<128xi32>
    %11 = cmpi less_than %9, %10, signed : tile<128xi32> -> tile<128xi1>
    %12 = constant <f64: 0.0> : tile<128xf64>
    %13 = constant <i32: 0> : tile<i32>
    %14 = addi %5, %13 : tile<i32>
    %15 = reshape %14 : tile<i32> -> tile<1xi32>
    %16 = broadcast %15 : tile<1xi32> -> tile<128xi32>
    %17 = iota : tile<128xi32>
    %18 = addi %16, %17 : tile<128xi32>
    %19 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %20 = broadcast %19 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %21 = offset %20, %18 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %22, %23 = load_ptr_tko weak %21, %11, %12 token=%0 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %24 = constant <i32: 0> : tile<i32>
    %25 = reshape %24 : tile<i32> -> tile<1xi32>
    %26 = broadcast %25 : tile<1xi32> -> tile<128xi32>
    %27 = iota : tile<128xi32>
    %28 = constant <i32: 0> : tile<128xi32>
    %29 = muli %27, %28 : tile<128xi32>
    %30 = addi %26, %29 : tile<128xi32>
    %31 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %32 = broadcast %31 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %33 = offset %32, %30 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %34, %35 = load_ptr_tko weak %33 token=%23 : tile<128xptr<f64>> -> tile<128xf64>, token
    %36 = mulf %22, %34 rounding<nearest_even> : tile<128xf64>
    %37 = addf %12, %36 rounding<nearest_even> : tile<128xf64>
    %38 = constant <i32: 1> : tile<i32>
    %39 = addi %5, %38 : tile<i32>
    %40 = reshape %39 : tile<i32> -> tile<1xi32>
    %41 = broadcast %40 : tile<1xi32> -> tile<128xi32>
    %42 = iota : tile<128xi32>
    %43 = addi %41, %42 : tile<128xi32>
    %44 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %45 = broadcast %44 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %46 = offset %45, %43 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %47, %48 = load_ptr_tko weak %46, %11, %12 token=%35 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %49 = constant <i32: 1> : tile<i32>
    %50 = reshape %49 : tile<i32> -> tile<1xi32>
    %51 = broadcast %50 : tile<1xi32> -> tile<128xi32>
    %52 = iota : tile<128xi32>
    %53 = constant <i32: 0> : tile<128xi32>
    %54 = muli %52, %53 : tile<128xi32>
    %55 = addi %51, %54 : tile<128xi32>
    %56 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %57 = broadcast %56 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %58 = offset %57, %55 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %59, %60 = load_ptr_tko weak %58 token=%48 : tile<128xptr<f64>> -> tile<128xf64>, token
    %61 = mulf %47, %59 rounding<nearest_even> : tile<128xf64>
    %62 = addf %37, %61 rounding<nearest_even> : tile<128xf64>
    %63 = constant <i32: 2> : tile<i32>
    %64 = addi %5, %63 : tile<i32>
    %65 = reshape %64 : tile<i32> -> tile<1xi32>
    %66 = broadcast %65 : tile<1xi32> -> tile<128xi32>
    %67 = iota : tile<128xi32>
    %68 = addi %66, %67 : tile<128xi32>
    %69 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %70 = broadcast %69 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %71 = offset %70, %68 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %72, %73 = load_ptr_tko weak %71, %11, %12 token=%60 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %74 = constant <i32: 2> : tile<i32>
    %75 = reshape %74 : tile<i32> -> tile<1xi32>
    %76 = broadcast %75 : tile<1xi32> -> tile<128xi32>
    %77 = iota : tile<128xi32>
    %78 = constant <i32: 0> : tile<128xi32>
    %79 = muli %77, %78 : tile<128xi32>
    %80 = addi %76, %79 : tile<128xi32>
    %81 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %82 = broadcast %81 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %83 = offset %82, %80 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %84, %85 = load_ptr_tko weak %83 token=%73 : tile<128xptr<f64>> -> tile<128xf64>, token
    %86 = mulf %72, %84 rounding<nearest_even> : tile<128xf64>
    %87 = addf %62, %86 rounding<nearest_even> : tile<128xf64>
    %88 = constant <i32: 3> : tile<i32>
    %89 = addi %5, %88 : tile<i32>
    %90 = reshape %89 : tile<i32> -> tile<1xi32>
    %91 = broadcast %90 : tile<1xi32> -> tile<128xi32>
    %92 = iota : tile<128xi32>
    %93 = addi %91, %92 : tile<128xi32>
    %94 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %95 = broadcast %94 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %96 = offset %95, %93 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %97, %98 = load_ptr_tko weak %96, %11, %12 token=%85 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %99 = constant <i32: 3> : tile<i32>
    %100 = reshape %99 : tile<i32> -> tile<1xi32>
    %101 = broadcast %100 : tile<1xi32> -> tile<128xi32>
    %102 = iota : tile<128xi32>
    %103 = constant <i32: 0> : tile<128xi32>
    %104 = muli %102, %103 : tile<128xi32>
    %105 = addi %101, %104 : tile<128xi32>
    %106 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %107 = broadcast %106 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %108 = offset %107, %105 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %109, %110 = load_ptr_tko weak %108 token=%98 : tile<128xptr<f64>> -> tile<128xf64>, token
    %111 = mulf %97, %109 rounding<nearest_even> : tile<128xf64>
    %112 = addf %87, %111 rounding<nearest_even> : tile<128xf64>
    %113 = constant <i32: 4> : tile<i32>
    %114 = addi %5, %113 : tile<i32>
    %115 = reshape %114 : tile<i32> -> tile<1xi32>
    %116 = broadcast %115 : tile<1xi32> -> tile<128xi32>
    %117 = iota : tile<128xi32>
    %118 = addi %116, %117 : tile<128xi32>
    %119 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %120 = broadcast %119 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %121 = offset %120, %118 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %122, %123 = load_ptr_tko weak %121, %11, %12 token=%110 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %124 = constant <i32: 4> : tile<i32>
    %125 = reshape %124 : tile<i32> -> tile<1xi32>
    %126 = broadcast %125 : tile<1xi32> -> tile<128xi32>
    %127 = iota : tile<128xi32>
    %128 = constant <i32: 0> : tile<128xi32>
    %129 = muli %127, %128 : tile<128xi32>
    %130 = addi %126, %129 : tile<128xi32>
    %131 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %132 = broadcast %131 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %133 = offset %132, %130 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %134, %135 = load_ptr_tko weak %133 token=%123 : tile<128xptr<f64>> -> tile<128xf64>, token
    %136 = mulf %122, %134 rounding<nearest_even> : tile<128xf64>
    %137 = addf %112, %136 rounding<nearest_even> : tile<128xf64>
    %138 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %139 = broadcast %138 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %140 = offset %139, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %141 = store_ptr_tko weak %140, %137, %11 token=%135 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    return
  }
}
