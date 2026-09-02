cuda_tile.module @m {
  entry @ppo_loss(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 1024> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<1024xi32>
    %8 = iota : tile<1024xi32>
    %9 = addi %7, %8 : tile<1024xi32>
    %10 = constant <i32: 1000> : tile<1024xi32>
    %11 = cmpi less_than %9, %10, signed : tile<1024xi32> -> tile<1024xi1>
    %12 = constant <f64: 0.0> : tile<1024xf64>
    %13 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %14 = broadcast %13 : tile<1xptr<f64>> -> tile<1024xptr<f64>>
    %15 = offset %14, %9 : tile<1024xptr<f64>>, tile<1024xi32> -> tile<1024xptr<f64>>
    %16, %17 = load_ptr_tko weak %15, %11, %12 token=%0 : tile<1024xptr<f64>>, tile<1024xi1>, tile<1024xf64> -> tile<1024xf64>, token
    %18 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %19 = broadcast %18 : tile<1xptr<f64>> -> tile<1024xptr<f64>>
    %20 = offset %19, %9 : tile<1024xptr<f64>>, tile<1024xi32> -> tile<1024xptr<f64>>
    %21, %22 = load_ptr_tko weak %20, %11, %12 token=%17 : tile<1024xptr<f64>>, tile<1024xi1>, tile<1024xf64> -> tile<1024xf64>, token
    %23 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %24 = broadcast %23 : tile<1xptr<f64>> -> tile<1024xptr<f64>>
    %25 = offset %24, %9 : tile<1024xptr<f64>>, tile<1024xi32> -> tile<1024xptr<f64>>
    %26, %27 = load_ptr_tko weak %25, %11, %12 token=%22 : tile<1024xptr<f64>>, tile<1024xi1>, tile<1024xf64> -> tile<1024xf64>, token
    %28 = subf %16, %21 rounding<nearest_even> : tile<1024xf64>
    %29 = exp %28 : tile<1024xf64>
    %30 = constant <f64: 0.8> : tile<1024xf64>
    %31 = constant <f64: 1.2> : tile<1024xf64>
    %32 = maxf %29, %30 : tile<1024xf64>
    %33 = minf %32, %31 : tile<1024xf64>
    %34 = mulf %29, %26 rounding<nearest_even> : tile<1024xf64>
    %35 = mulf %33, %26 rounding<nearest_even> : tile<1024xf64>
    %36 = minf %34, %35 : tile<1024xf64>
    %37 = select %11, %36, %12 : tile<1024xi1>, tile<1024xf64>
    %38 = reduce %37 dim=0 identities=[0.0 : f64] : tile<1024xf64> -> tile<f64> (%39: tile<f64>, %40: tile<f64>) {
      %41 = addf %39, %40 rounding<nearest_even> : tile<f64>
      yield %41 : tile<f64>
    }
    %42 = reshape %38 : tile<f64> -> tile<1xf64>
    %43 = broadcast %42 : tile<1xf64> -> tile<1xf64>
    %44 = constant <f64: 1000.0> : tile<1xf64>
    %45 = divf %43, %44 rounding<nearest_even> : tile<1xf64>
    %46 = negf %45 : tile<1xf64>
    %47 = constant <i32: 1> : tile<i32>
    %48 = muli %1, %47 : tile<i32>
    %49 = reshape %48 : tile<i32> -> tile<1xi32>
    %50 = broadcast %49 : tile<1xi32> -> tile<1xi32>
    %51 = iota : tile<1xi32>
    %52 = addi %50, %51 : tile<1xi32>
    %53 = reshape %arg3 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %54 = broadcast %53 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %55 = offset %54, %52 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %56 = store_ptr_tko weak %55, %46 token=%27 : tile<1xptr<f64>>, tile<1xf64> -> token
    return
  }
}
