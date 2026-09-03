cuda_tile.module @m {
  entry @batch_norm(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = reshape %1 : tile<i32> -> tile<1xi32>
    %5 = broadcast %4 : tile<1xi32> -> tile<128xi32>
    %6 = iota : tile<128xi32>
    %7 = constant <i32: 64> : tile<128xi32>
    %8 = muli %6, %7 : tile<128xi32>
    %9 = addi %5, %8 : tile<128xi32>
    %10 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %11 = broadcast %10 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %12 = offset %11, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %13, %14 = load_ptr_tko weak %12 token=%0 : tile<128xptr<f64>> -> tile<128xf64>, token
    %15 = reshape %1 : tile<i32> -> tile<1xi32>
    %16 = broadcast %15 : tile<1xi32> -> tile<128xi32>
    %17 = iota : tile<128xi32>
    %18 = constant <i32: 0> : tile<128xi32>
    %19 = muli %17, %18 : tile<128xi32>
    %20 = addi %16, %19 : tile<128xi32>
    %21 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %22 = broadcast %21 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %23 = offset %22, %20 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %24, %25 = load_ptr_tko weak %23 token=%14 : tile<128xptr<f64>> -> tile<128xf64>, token
    %26 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %27 = broadcast %26 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %28 = offset %27, %20 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %29, %30 = load_ptr_tko weak %28 token=%25 : tile<128xptr<f64>> -> tile<128xf64>, token
    %31 = constant <f64: 128.0> : tile<128xf64>
    %32 = reduce %13 dim=0 identities=[0.0 : f64] : tile<128xf64> -> tile<f64> (%33: tile<f64>, %34: tile<f64>) {
      %35 = addf %33, %34 rounding<nearest_even> : tile<f64>
      yield %35 : tile<f64>
    }
    %36 = reshape %32 : tile<f64> -> tile<1xf64>
    %37 = broadcast %36 : tile<1xf64> -> tile<128xf64>
    %38 = divf %37, %31 rounding<nearest_even> : tile<128xf64>
    %39 = subf %13, %38 rounding<nearest_even> : tile<128xf64>
    %40 = mulf %39, %39 rounding<nearest_even> : tile<128xf64>
    %41 = reduce %40 dim=0 identities=[0.0 : f64] : tile<128xf64> -> tile<f64> (%42: tile<f64>, %43: tile<f64>) {
      %44 = addf %42, %43 rounding<nearest_even> : tile<f64>
      yield %44 : tile<f64>
    }
    %45 = reshape %41 : tile<f64> -> tile<1xf64>
    %46 = broadcast %45 : tile<1xf64> -> tile<128xf64>
    %47 = divf %46, %31 rounding<nearest_even> : tile<128xf64>
    %48 = constant <f64: 1.0E-5> : tile<128xf64>
    %49 = addf %47, %48 rounding<nearest_even> : tile<128xf64>
    %50 = sqrt %49 rounding<nearest_even> : tile<128xf64>
    %51 = divf %39, %50 rounding<nearest_even> : tile<128xf64>
    %52 = mulf %51, %24 rounding<nearest_even> : tile<128xf64>
    %53 = addf %52, %29 rounding<nearest_even> : tile<128xf64>
    %54 = reshape %arg3 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %55 = broadcast %54 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %56 = offset %55, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %57 = store_ptr_tko weak %56, %53 token=%30 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
