cuda_tile.module @m {
  entry @attr_ftof(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 1408> : tile<i32>
    %7 = muli %1, %6 : tile<i32>
    %8 = reshape %5 : tile<i32> -> tile<1xi32>
    %9 = broadcast %8 : tile<1xi32> -> tile<128xi32>
    %10 = iota : tile<128xi32>
    %11 = addi %9, %10 : tile<128xi32>
    %12 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %13 = broadcast %12 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %14 = offset %13, %11 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %15, %16 = load_ptr_tko weak %14 token=%0 : tile<128xptr<f64>> -> tile<128xf64>, token
    %17 = ftof %15 rounding<nearest_even> : tile<128xf64> -> tile<128xf32>
    %18 = constant <i32: 0> : tile<i32>
    %19 = addi %7, %18 : tile<i32>
    %20 = ftof %17 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %21 = reshape %19 : tile<i32> -> tile<1xi32>
    %22 = broadcast %21 : tile<1xi32> -> tile<128xi32>
    %23 = iota : tile<128xi32>
    %24 = addi %22, %23 : tile<128xi32>
    %25 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %26 = broadcast %25 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %27 = offset %26, %24 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %28 = store_ptr_tko weak %27, %20 token=%16 : tile<128xptr<f64>>, tile<128xf64> -> token
    %29 = constant <i32: 128> : tile<i32>
    %30 = addi %7, %29 : tile<i32>
    %31 = ftof %15 rounding<zero> : tile<128xf64> -> tile<128xf32>
    %32 = ftof %31 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %33 = reshape %30 : tile<i32> -> tile<1xi32>
    %34 = broadcast %33 : tile<1xi32> -> tile<128xi32>
    %35 = iota : tile<128xi32>
    %36 = addi %34, %35 : tile<128xi32>
    %37 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %38 = broadcast %37 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %39 = offset %38, %36 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %40 = store_ptr_tko weak %39, %32 token=%28 : tile<128xptr<f64>>, tile<128xf64> -> token
    %41 = constant <i32: 256> : tile<i32>
    %42 = addi %7, %41 : tile<i32>
    %43 = ftof %15 rounding<negative_inf> : tile<128xf64> -> tile<128xf32>
    %44 = ftof %43 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %45 = reshape %42 : tile<i32> -> tile<1xi32>
    %46 = broadcast %45 : tile<1xi32> -> tile<128xi32>
    %47 = iota : tile<128xi32>
    %48 = addi %46, %47 : tile<128xi32>
    %49 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %50 = broadcast %49 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %51 = offset %50, %48 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %52 = store_ptr_tko weak %51, %44 token=%40 : tile<128xptr<f64>>, tile<128xf64> -> token
    %53 = constant <i32: 384> : tile<i32>
    %54 = addi %7, %53 : tile<i32>
    %55 = ftof %15 rounding<positive_inf> : tile<128xf64> -> tile<128xf32>
    %56 = ftof %55 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %57 = reshape %54 : tile<i32> -> tile<1xi32>
    %58 = broadcast %57 : tile<1xi32> -> tile<128xi32>
    %59 = iota : tile<128xi32>
    %60 = addi %58, %59 : tile<128xi32>
    %61 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %62 = broadcast %61 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %63 = offset %62, %60 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %64 = store_ptr_tko weak %63, %56 token=%52 : tile<128xptr<f64>>, tile<128xf64> -> token
    %65 = constant <i32: 512> : tile<i32>
    %66 = addi %7, %65 : tile<i32>
    %67 = ftof %17 rounding<nearest_even> : tile<128xf32> -> tile<128xtf32>
    %68 = ftof %67 rounding<nearest_even> : tile<128xtf32> -> tile<128xf64>
    %69 = reshape %66 : tile<i32> -> tile<1xi32>
    %70 = broadcast %69 : tile<1xi32> -> tile<128xi32>
    %71 = iota : tile<128xi32>
    %72 = addi %70, %71 : tile<128xi32>
    %73 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %74 = broadcast %73 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %75 = offset %74, %72 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %76 = store_ptr_tko weak %75, %68 token=%64 : tile<128xptr<f64>>, tile<128xf64> -> token
    %77 = constant <i32: 640> : tile<i32>
    %78 = addi %7, %77 : tile<i32>
    %79 = ftof %17 rounding<zero> : tile<128xf32> -> tile<128xtf32>
    %80 = ftof %79 rounding<nearest_even> : tile<128xtf32> -> tile<128xf64>
    %81 = reshape %78 : tile<i32> -> tile<1xi32>
    %82 = broadcast %81 : tile<1xi32> -> tile<128xi32>
    %83 = iota : tile<128xi32>
    %84 = addi %82, %83 : tile<128xi32>
    %85 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %86 = broadcast %85 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %87 = offset %86, %84 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %88 = store_ptr_tko weak %87, %80 token=%76 : tile<128xptr<f64>>, tile<128xf64> -> token
    %89 = constant <i32: 768> : tile<i32>
    %90 = addi %7, %89 : tile<i32>
    %91 = ftof %17 rounding<nearest_away> : tile<128xf32> -> tile<128xtf32>
    %92 = ftof %91 rounding<nearest_away> : tile<128xtf32> -> tile<128xf64>
    %93 = reshape %90 : tile<i32> -> tile<1xi32>
    %94 = broadcast %93 : tile<1xi32> -> tile<128xi32>
    %95 = iota : tile<128xi32>
    %96 = addi %94, %95 : tile<128xi32>
    %97 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %98 = broadcast %97 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %99 = offset %98, %96 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %100 = store_ptr_tko weak %99, %92 token=%88 : tile<128xptr<f64>>, tile<128xf64> -> token
    %101 = constant <i32: 896> : tile<i32>
    %102 = addi %7, %101 : tile<i32>
    %103 = ftof %17 rounding<nearest_even> : tile<128xf32> -> tile<128xf16>
    %104 = ftof %103 rounding<nearest_even> : tile<128xf16> -> tile<128xf64>
    %105 = reshape %102 : tile<i32> -> tile<1xi32>
    %106 = broadcast %105 : tile<1xi32> -> tile<128xi32>
    %107 = iota : tile<128xi32>
    %108 = addi %106, %107 : tile<128xi32>
    %109 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %110 = broadcast %109 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %111 = offset %110, %108 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %112 = store_ptr_tko weak %111, %104 token=%100 : tile<128xptr<f64>>, tile<128xf64> -> token
    %113 = constant <i32: 1024> : tile<i32>
    %114 = addi %7, %113 : tile<i32>
    %115 = ftof %17 rounding<zero> : tile<128xf32> -> tile<128xf16>
    %116 = ftof %115 rounding<zero> : tile<128xf16> -> tile<128xf64>
    %117 = reshape %114 : tile<i32> -> tile<1xi32>
    %118 = broadcast %117 : tile<1xi32> -> tile<128xi32>
    %119 = iota : tile<128xi32>
    %120 = addi %118, %119 : tile<128xi32>
    %121 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %122 = broadcast %121 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %123 = offset %122, %120 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %124 = store_ptr_tko weak %123, %116 token=%112 : tile<128xptr<f64>>, tile<128xf64> -> token
    %125 = constant <i32: 1152> : tile<i32>
    %126 = addi %7, %125 : tile<i32>
    %127 = ftof %17 rounding<nearest_even> : tile<128xf32> -> tile<128xbf16>
    %128 = ftof %127 rounding<nearest_even> : tile<128xbf16> -> tile<128xf64>
    %129 = reshape %126 : tile<i32> -> tile<1xi32>
    %130 = broadcast %129 : tile<1xi32> -> tile<128xi32>
    %131 = iota : tile<128xi32>
    %132 = addi %130, %131 : tile<128xi32>
    %133 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %134 = broadcast %133 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %135 = offset %134, %132 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %136 = store_ptr_tko weak %135, %128 token=%124 : tile<128xptr<f64>>, tile<128xf64> -> token
    %137 = constant <i32: 1280> : tile<i32>
    %138 = addi %7, %137 : tile<i32>
    %139 = ftof %17 rounding<zero> : tile<128xf32> -> tile<128xbf16>
    %140 = ftof %139 rounding<positive_inf> : tile<128xbf16> -> tile<128xf64>
    %141 = reshape %138 : tile<i32> -> tile<1xi32>
    %142 = broadcast %141 : tile<1xi32> -> tile<128xi32>
    %143 = iota : tile<128xi32>
    %144 = addi %142, %143 : tile<128xi32>
    %145 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %146 = broadcast %145 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %147 = offset %146, %144 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %148 = store_ptr_tko weak %147, %140 token=%136 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
