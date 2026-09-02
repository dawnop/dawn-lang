cuda_tile.module @m {
  entry @dpo_loss(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>, %arg4: tile<ptr<f64>>) {
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
    %13 = constant <f64: 1.0> : tile<1024xf64>
    %14 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %15 = broadcast %14 : tile<1xptr<f64>> -> tile<1024xptr<f64>>
    %16 = offset %15, %9 : tile<1024xptr<f64>>, tile<1024xi32> -> tile<1024xptr<f64>>
    %17, %18 = load_ptr_tko weak %16, %11, %12 token=%0 : tile<1024xptr<f64>>, tile<1024xi1>, tile<1024xf64> -> tile<1024xf64>, token
    %19 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %20 = broadcast %19 : tile<1xptr<f64>> -> tile<1024xptr<f64>>
    %21 = offset %20, %9 : tile<1024xptr<f64>>, tile<1024xi32> -> tile<1024xptr<f64>>
    %22, %23 = load_ptr_tko weak %21, %11, %12 token=%18 : tile<1024xptr<f64>>, tile<1024xi1>, tile<1024xf64> -> tile<1024xf64>, token
    %24 = subf %17, %22 rounding<nearest_even> : tile<1024xf64>
    %25 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %26 = broadcast %25 : tile<1xptr<f64>> -> tile<1024xptr<f64>>
    %27 = offset %26, %9 : tile<1024xptr<f64>>, tile<1024xi32> -> tile<1024xptr<f64>>
    %28, %29 = load_ptr_tko weak %27, %11, %12 token=%23 : tile<1024xptr<f64>>, tile<1024xi1>, tile<1024xf64> -> tile<1024xf64>, token
    %30 = reshape %arg3 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %31 = broadcast %30 : tile<1xptr<f64>> -> tile<1024xptr<f64>>
    %32 = offset %31, %9 : tile<1024xptr<f64>>, tile<1024xi32> -> tile<1024xptr<f64>>
    %33, %34 = load_ptr_tko weak %32, %11, %12 token=%29 : tile<1024xptr<f64>>, tile<1024xi1>, tile<1024xf64> -> tile<1024xf64>, token
    %35 = subf %28, %33 rounding<nearest_even> : tile<1024xf64>
    %36 = constant <f64: 0.1> : tile<1024xf64>
    %37 = subf %24, %35 rounding<nearest_even> : tile<1024xf64>
    %38 = mulf %36, %37 rounding<nearest_even> : tile<1024xf64>
    %39 = negf %38 : tile<1024xf64>
    %40 = exp %39 : tile<1024xf64>
    %41 = addf %13, %40 rounding<nearest_even> : tile<1024xf64>
    %42 = divf %13, %41 rounding<nearest_even> : tile<1024xf64>
    %43 = log %42 : tile<1024xf64>
    %44 = select %11, %43, %12 : tile<1024xi1>, tile<1024xf64>
    %45 = reduce %44 dim=0 identities=[0.0 : f64] : tile<1024xf64> -> tile<f64> (%46: tile<f64>, %47: tile<f64>) {
      %48 = addf %46, %47 rounding<nearest_even> : tile<f64>
      yield %48 : tile<f64>
    }
    %49 = reshape %45 : tile<f64> -> tile<1xf64>
    %50 = broadcast %49 : tile<1xf64> -> tile<1xf64>
    %51 = constant <f64: 1000.0> : tile<1xf64>
    %52 = divf %50, %51 rounding<nearest_even> : tile<1xf64>
    %53 = negf %52 : tile<1xf64>
    %54 = constant <i32: 1> : tile<i32>
    %55 = muli %1, %54 : tile<i32>
    %56 = reshape %55 : tile<i32> -> tile<1xi32>
    %57 = broadcast %56 : tile<1xi32> -> tile<1xi32>
    %58 = iota : tile<1xi32>
    %59 = addi %57, %58 : tile<1xi32>
    %60 = reshape %arg4 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %61 = broadcast %60 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %62 = offset %61, %59 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %63 = store_ptr_tko weak %62, %53 token=%34 : tile<1xptr<f64>>, tile<1xf64> -> token
    return
  }
}
