cuda_tile.module @m {
  entry @f16_ops(%arg0: tile<ptr<f16>>, %arg1: tile<ptr<f16>>, %arg2: tile<ptr<f16>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<128xi32>
    %8 = iota : tile<128xi32>
    %9 = addi %7, %8 : tile<128xi32>
    %10 = constant <i32: 1000> : tile<128xi32>
    %11 = cmpi less_than %9, %10, signed : tile<128xi32> -> tile<128xi1>
    %12 = constant <f16: 0.0> : tile<128xf16>
    %13 = reshape %arg0 : tile<ptr<f16>> -> tile<1xptr<f16>>
    %14 = broadcast %13 : tile<1xptr<f16>> -> tile<128xptr<f16>>
    %15 = offset %14, %9 : tile<128xptr<f16>>, tile<128xi32> -> tile<128xptr<f16>>
    %16, %17 = load_ptr_tko weak %15, %11, %12 token=%0 : tile<128xptr<f16>>, tile<128xi1>, tile<128xf16> -> tile<128xf16>, token
    %18 = reshape %arg1 : tile<ptr<f16>> -> tile<1xptr<f16>>
    %19 = broadcast %18 : tile<1xptr<f16>> -> tile<128xptr<f16>>
    %20 = offset %19, %9 : tile<128xptr<f16>>, tile<128xi32> -> tile<128xptr<f16>>
    %21, %22 = load_ptr_tko weak %20, %11, %12 token=%17 : tile<128xptr<f16>>, tile<128xi1>, tile<128xf16> -> tile<128xf16>, token
    %23 = addf %16, %21 rounding<nearest_even> : tile<128xf16>
    %24 = mulf %23, %16 rounding<nearest_even> : tile<128xf16>
    %25 = subf %24, %21 rounding<nearest_even> : tile<128xf16>
    %26 = reshape %arg2 : tile<ptr<f16>> -> tile<1xptr<f16>>
    %27 = broadcast %26 : tile<1xptr<f16>> -> tile<128xptr<f16>>
    %28 = offset %27, %9 : tile<128xptr<f16>>, tile<128xi32> -> tile<128xptr<f16>>
    %29 = store_ptr_tko weak %28, %25, %11 token=%22 : tile<128xptr<f16>>, tile<128xf16>, tile<128xi1> -> token
    return
  }
}
