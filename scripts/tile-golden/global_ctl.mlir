cuda_tile.module @m {
  entry @global_ctl(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<128xi32>
    %8 = iota : tile<128xi32>
    %9 = addi %7, %8 : tile<128xi32>
    %10 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %11 = broadcast %10 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %12 = offset %11, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %13, %14 = load_ptr_tko weak %12 token=%0 : tile<128xptr<f64>> -> tile<128xf64>, token
    %15 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %16 = broadcast %15 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %17 = offset %16, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %18, %19 = load_ptr_tko weak %17 token=%14 : tile<128xptr<f64>> -> tile<128xf64>, token
    %20 = addf %18, %13 rounding<nearest_even> : tile<128xf64>
    %21 = reshape %arg3 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %22 = broadcast %21 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %23 = offset %22, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %24 = store_ptr_tko weak %23, %20 token=%19 : tile<128xptr<f64>>, tile<128xf64> -> token
    %25 = constant <i32: 128> : tile<i32>
    %26 = addi %5, %25 : tile<i32>
    %27 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %28 = broadcast %27 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %29 = offset %28, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %30, %31 = load_ptr_tko weak %29 token=%24 : tile<128xptr<f64>> -> tile<128xf64>, token
    %32 = addf %30, %13 rounding<nearest_even> : tile<128xf64>
    %33 = reshape %26 : tile<i32> -> tile<1xi32>
    %34 = broadcast %33 : tile<1xi32> -> tile<128xi32>
    %35 = iota : tile<128xi32>
    %36 = addi %34, %35 : tile<128xi32>
    %37 = reshape %arg3 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %38 = broadcast %37 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %39 = offset %38, %36 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %40 = store_ptr_tko weak %39, %32 token=%31 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
