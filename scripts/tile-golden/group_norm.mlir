cuda_tile.module @m {
  entry @group_norm(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7 = constant <i32: 256> : tile<i32>
    %8 = muli %1, %7 : tile<i32>
    %9 = constant <i32: 64> : tile<i32>
    %10 = muli %5, %9 : tile<i32>
    %11 = addi %8, %10 : tile<i32>
    %12 = reshape %11 : tile<i32> -> tile<1x1xi32>
    %13 = broadcast %12 : tile<1x1xi32> -> tile<2x32xi32>
    %14 = iota : tile<2xi32>
    %15 = reshape %14 : tile<2xi32> -> tile<2x1xi32>
    %16 = broadcast %15 : tile<2x1xi32> -> tile<2x32xi32>
    %17 = constant <i32: 32> : tile<2x32xi32>
    %18 = muli %16, %17 : tile<2x32xi32>
    %19 = addi %13, %18 : tile<2x32xi32>
    %20 = iota : tile<32xi32>
    %21 = reshape %20 : tile<32xi32> -> tile<1x32xi32>
    %22 = broadcast %21 : tile<1x32xi32> -> tile<2x32xi32>
    %23 = addi %19, %22 : tile<2x32xi32>
    %24 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %25 = broadcast %24 : tile<1x1xptr<f64>> -> tile<2x32xptr<f64>>
    %26 = offset %25, %23 : tile<2x32xptr<f64>>, tile<2x32xi32> -> tile<2x32xptr<f64>>
    %27, %28 = load_ptr_tko weak %26 token=%0 : tile<2x32xptr<f64>> -> tile<2x32xf64>, token
    %29 = constant <i32: 2> : tile<i32>
    %30 = muli %5, %29 : tile<i32>
    %31 = reshape %30 : tile<i32> -> tile<1x1xi32>
    %32 = broadcast %31 : tile<1x1xi32> -> tile<2x32xi32>
    %33 = iota : tile<2xi32>
    %34 = reshape %33 : tile<2xi32> -> tile<2x1xi32>
    %35 = broadcast %34 : tile<2x1xi32> -> tile<2x32xi32>
    %36 = addi %32, %35 : tile<2x32xi32>
    %37 = iota : tile<32xi32>
    %38 = reshape %37 : tile<32xi32> -> tile<1x32xi32>
    %39 = broadcast %38 : tile<1x32xi32> -> tile<2x32xi32>
    %40 = constant <i32: 0> : tile<2x32xi32>
    %41 = muli %39, %40 : tile<2x32xi32>
    %42 = addi %36, %41 : tile<2x32xi32>
    %43 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %44 = broadcast %43 : tile<1x1xptr<f64>> -> tile<2x32xptr<f64>>
    %45 = offset %44, %42 : tile<2x32xptr<f64>>, tile<2x32xi32> -> tile<2x32xptr<f64>>
    %46, %47 = load_ptr_tko weak %45 token=%28 : tile<2x32xptr<f64>> -> tile<2x32xf64>, token
    %48 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %49 = broadcast %48 : tile<1x1xptr<f64>> -> tile<2x32xptr<f64>>
    %50 = offset %49, %42 : tile<2x32xptr<f64>>, tile<2x32xi32> -> tile<2x32xptr<f64>>
    %51, %52 = load_ptr_tko weak %50 token=%47 : tile<2x32xptr<f64>> -> tile<2x32xf64>, token
    %53 = constant <f64: 64.0> : tile<2x32xf64>
    %54 = reduce %27 dim=1 identities=[0.0 : f64] : tile<2x32xf64> -> tile<2xf64> (%55: tile<f64>, %56: tile<f64>) {
      %57 = addf %55, %56 rounding<nearest_even> : tile<f64>
      yield %57 : tile<f64>
    }
    %58 = reduce %54 dim=0 identities=[0.0 : f64] : tile<2xf64> -> tile<f64> (%59: tile<f64>, %60: tile<f64>) {
      %61 = addf %59, %60 rounding<nearest_even> : tile<f64>
      yield %61 : tile<f64>
    }
    %62 = reshape %58 : tile<f64> -> tile<1x1xf64>
    %63 = broadcast %62 : tile<1x1xf64> -> tile<2x32xf64>
    %64 = divf %63, %53 rounding<nearest_even> : tile<2x32xf64>
    %65 = subf %27, %64 rounding<nearest_even> : tile<2x32xf64>
    %66 = mulf %65, %65 rounding<nearest_even> : tile<2x32xf64>
    %67 = reduce %66 dim=1 identities=[0.0 : f64] : tile<2x32xf64> -> tile<2xf64> (%68: tile<f64>, %69: tile<f64>) {
      %70 = addf %68, %69 rounding<nearest_even> : tile<f64>
      yield %70 : tile<f64>
    }
    %71 = reduce %67 dim=0 identities=[0.0 : f64] : tile<2xf64> -> tile<f64> (%72: tile<f64>, %73: tile<f64>) {
      %74 = addf %72, %73 rounding<nearest_even> : tile<f64>
      yield %74 : tile<f64>
    }
    %75 = reshape %71 : tile<f64> -> tile<1x1xf64>
    %76 = broadcast %75 : tile<1x1xf64> -> tile<2x32xf64>
    %77 = divf %76, %53 rounding<nearest_even> : tile<2x32xf64>
    %78 = constant <f64: 1.0E-5> : tile<2x32xf64>
    %79 = addf %77, %78 rounding<nearest_even> : tile<2x32xf64>
    %80 = sqrt %79 rounding<nearest_even> : tile<2x32xf64>
    %81 = divf %65, %80 rounding<nearest_even> : tile<2x32xf64>
    %82 = mulf %81, %46 rounding<nearest_even> : tile<2x32xf64>
    %83 = addf %82, %51 rounding<nearest_even> : tile<2x32xf64>
    %84 = reshape %arg3 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %85 = broadcast %84 : tile<1x1xptr<f64>> -> tile<2x32xptr<f64>>
    %86 = offset %85, %23 : tile<2x32xptr<f64>>, tile<2x32xi32> -> tile<2x32xptr<f64>>
    %87 = store_ptr_tko weak %86, %83 token=%52 : tile<2x32xptr<f64>>, tile<2x32xf64> -> token
    return
  }
}
