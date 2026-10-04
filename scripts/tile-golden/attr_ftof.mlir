cuda_tile.module @m {
  entry @attr_ftof(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 1408> : tile<i32>
    %7 = muli %1, %6 : tile<i32>
    %8, %9, %10 = get_num_tile_blocks : tile<i32>
    %11 = constant <i32: 128> : tile<i32>
    %12 = muli %8, %11 : tile<i32>
    %13 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %14 = make_tensor_view %13, shape = [%12], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %15 = make_partition_view %14 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %16, %17, %18 = get_tile_block_id : tile<i32>
    %19, %20 = load_view_tko weak %15[%16] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %21 = ftof %19 rounding<nearest_even> : tile<128xf64> -> tile<128xf32>
    %22 = constant <i32: 0> : tile<i32>
    %23 = addi %7, %22 : tile<i32>
    %24 = ftof %21 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %25 = reshape %23 : tile<i32> -> tile<1xi32>
    %26 = broadcast %25 : tile<1xi32> -> tile<128xi32>
    %27 = iota : tile<128xi32>
    %28 = addi %26, %27 : tile<128xi32>
    %29 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %30 = broadcast %29 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %31 = offset %30, %28 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %32 = store_ptr_tko weak %31, %24 token=%20 : tile<128xptr<f64>>, tile<128xf64> -> token
    %33 = constant <i32: 128> : tile<i32>
    %34 = addi %7, %33 : tile<i32>
    %35 = ftof %19 rounding<zero> : tile<128xf64> -> tile<128xf32>
    %36 = ftof %35 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %37 = reshape %34 : tile<i32> -> tile<1xi32>
    %38 = broadcast %37 : tile<1xi32> -> tile<128xi32>
    %39 = iota : tile<128xi32>
    %40 = addi %38, %39 : tile<128xi32>
    %41 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %42 = broadcast %41 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %43 = offset %42, %40 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %44 = store_ptr_tko weak %43, %36 token=%32 : tile<128xptr<f64>>, tile<128xf64> -> token
    %45 = constant <i32: 256> : tile<i32>
    %46 = addi %7, %45 : tile<i32>
    %47 = ftof %19 rounding<negative_inf> : tile<128xf64> -> tile<128xf32>
    %48 = ftof %47 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %49 = reshape %46 : tile<i32> -> tile<1xi32>
    %50 = broadcast %49 : tile<1xi32> -> tile<128xi32>
    %51 = iota : tile<128xi32>
    %52 = addi %50, %51 : tile<128xi32>
    %53 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %54 = broadcast %53 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %55 = offset %54, %52 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %56 = store_ptr_tko weak %55, %48 token=%44 : tile<128xptr<f64>>, tile<128xf64> -> token
    %57 = constant <i32: 384> : tile<i32>
    %58 = addi %7, %57 : tile<i32>
    %59 = ftof %19 rounding<positive_inf> : tile<128xf64> -> tile<128xf32>
    %60 = ftof %59 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %61 = reshape %58 : tile<i32> -> tile<1xi32>
    %62 = broadcast %61 : tile<1xi32> -> tile<128xi32>
    %63 = iota : tile<128xi32>
    %64 = addi %62, %63 : tile<128xi32>
    %65 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %66 = broadcast %65 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %67 = offset %66, %64 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %68 = store_ptr_tko weak %67, %60 token=%56 : tile<128xptr<f64>>, tile<128xf64> -> token
    %69 = constant <i32: 512> : tile<i32>
    %70 = addi %7, %69 : tile<i32>
    %71 = ftof %21 rounding<nearest_even> : tile<128xf32> -> tile<128xtf32>
    %72 = ftof %71 rounding<nearest_even> : tile<128xtf32> -> tile<128xf64>
    %73 = reshape %70 : tile<i32> -> tile<1xi32>
    %74 = broadcast %73 : tile<1xi32> -> tile<128xi32>
    %75 = iota : tile<128xi32>
    %76 = addi %74, %75 : tile<128xi32>
    %77 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %78 = broadcast %77 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %79 = offset %78, %76 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %80 = store_ptr_tko weak %79, %72 token=%68 : tile<128xptr<f64>>, tile<128xf64> -> token
    %81 = constant <i32: 640> : tile<i32>
    %82 = addi %7, %81 : tile<i32>
    %83 = ftof %21 rounding<zero> : tile<128xf32> -> tile<128xtf32>
    %84 = ftof %83 rounding<nearest_even> : tile<128xtf32> -> tile<128xf64>
    %85 = reshape %82 : tile<i32> -> tile<1xi32>
    %86 = broadcast %85 : tile<1xi32> -> tile<128xi32>
    %87 = iota : tile<128xi32>
    %88 = addi %86, %87 : tile<128xi32>
    %89 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %90 = broadcast %89 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %91 = offset %90, %88 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %92 = store_ptr_tko weak %91, %84 token=%80 : tile<128xptr<f64>>, tile<128xf64> -> token
    %93 = constant <i32: 768> : tile<i32>
    %94 = addi %7, %93 : tile<i32>
    %95 = ftof %21 rounding<nearest_away> : tile<128xf32> -> tile<128xtf32>
    %96 = ftof %95 rounding<nearest_away> : tile<128xtf32> -> tile<128xf64>
    %97 = reshape %94 : tile<i32> -> tile<1xi32>
    %98 = broadcast %97 : tile<1xi32> -> tile<128xi32>
    %99 = iota : tile<128xi32>
    %100 = addi %98, %99 : tile<128xi32>
    %101 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %102 = broadcast %101 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %103 = offset %102, %100 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %104 = store_ptr_tko weak %103, %96 token=%92 : tile<128xptr<f64>>, tile<128xf64> -> token
    %105 = constant <i32: 896> : tile<i32>
    %106 = addi %7, %105 : tile<i32>
    %107 = ftof %21 rounding<nearest_even> : tile<128xf32> -> tile<128xf16>
    %108 = ftof %107 rounding<nearest_even> : tile<128xf16> -> tile<128xf64>
    %109 = reshape %106 : tile<i32> -> tile<1xi32>
    %110 = broadcast %109 : tile<1xi32> -> tile<128xi32>
    %111 = iota : tile<128xi32>
    %112 = addi %110, %111 : tile<128xi32>
    %113 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %114 = broadcast %113 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %115 = offset %114, %112 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %116 = store_ptr_tko weak %115, %108 token=%104 : tile<128xptr<f64>>, tile<128xf64> -> token
    %117 = constant <i32: 1024> : tile<i32>
    %118 = addi %7, %117 : tile<i32>
    %119 = ftof %21 rounding<zero> : tile<128xf32> -> tile<128xf16>
    %120 = ftof %119 rounding<zero> : tile<128xf16> -> tile<128xf64>
    %121 = reshape %118 : tile<i32> -> tile<1xi32>
    %122 = broadcast %121 : tile<1xi32> -> tile<128xi32>
    %123 = iota : tile<128xi32>
    %124 = addi %122, %123 : tile<128xi32>
    %125 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %126 = broadcast %125 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %127 = offset %126, %124 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %128 = store_ptr_tko weak %127, %120 token=%116 : tile<128xptr<f64>>, tile<128xf64> -> token
    %129 = constant <i32: 1152> : tile<i32>
    %130 = addi %7, %129 : tile<i32>
    %131 = ftof %21 rounding<nearest_even> : tile<128xf32> -> tile<128xbf16>
    %132 = ftof %131 rounding<nearest_even> : tile<128xbf16> -> tile<128xf64>
    %133 = reshape %130 : tile<i32> -> tile<1xi32>
    %134 = broadcast %133 : tile<1xi32> -> tile<128xi32>
    %135 = iota : tile<128xi32>
    %136 = addi %134, %135 : tile<128xi32>
    %137 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %138 = broadcast %137 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %139 = offset %138, %136 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %140 = store_ptr_tko weak %139, %132 token=%128 : tile<128xptr<f64>>, tile<128xf64> -> token
    %141 = constant <i32: 1280> : tile<i32>
    %142 = addi %7, %141 : tile<i32>
    %143 = ftof %21 rounding<zero> : tile<128xf32> -> tile<128xbf16>
    %144 = ftof %143 rounding<positive_inf> : tile<128xbf16> -> tile<128xf64>
    %145 = reshape %142 : tile<i32> -> tile<1xi32>
    %146 = broadcast %145 : tile<1xi32> -> tile<128xi32>
    %147 = iota : tile<128xi32>
    %148 = addi %146, %147 : tile<128xi32>
    %149 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %150 = broadcast %149 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %151 = offset %150, %148 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %152 = store_ptr_tko weak %151, %144 token=%140 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
