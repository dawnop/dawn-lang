cuda_tile.module @m {
  entry @lin_attn_out(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <f64: 0.0> : tile<32x32xf64>
    %5 = constant <i32: 1024> : tile<i32>
    %6 = muli %1, %5 : tile<i32>
    %7 = reshape %6 : tile<i32> -> tile<1x1xi32>
    %8 = broadcast %7 : tile<1x1xi32> -> tile<32x32xi32>
    %9 = iota : tile<32xi32>
    %10 = reshape %9 : tile<32xi32> -> tile<32x1xi32>
    %11 = broadcast %10 : tile<32x1xi32> -> tile<32x32xi32>
    %12 = constant <i32: 32> : tile<32x32xi32>
    %13 = muli %11, %12 : tile<32x32xi32>
    %14 = addi %8, %13 : tile<32x32xi32>
    %15 = iota : tile<32xi32>
    %16 = reshape %15 : tile<32xi32> -> tile<1x32xi32>
    %17 = broadcast %16 : tile<1x32xi32> -> tile<32x32xi32>
    %18 = addi %14, %17 : tile<32x32xi32>
    %19 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %20 = broadcast %19 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %21 = offset %20, %18 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %22, %23 = load_ptr_tko weak %21 token=%0 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
    %24 = constant <f64: 0.0> : tile<32x32xf64>
    %25 = cmpf greater_than ordered %22, %24 : tile<32x32xf64> -> tile<32x32xi1>
    %26 = constant <f64: 1.0> : tile<32x32xf64>
    %27 = addf %22, %26 rounding<nearest_even> : tile<32x32xf64>
    %28 = exp %22 : tile<32x32xf64>
    %29 = select %25, %27, %28 : tile<32x32xi1>, tile<32x32xf64>
    %30 = constant <i32: 0> : tile<i32>
    %31 = reshape %30 : tile<i32> -> tile<1x1xi32>
    %32 = broadcast %31 : tile<1x1xi32> -> tile<32x32xi32>
    %33 = iota : tile<32xi32>
    %34 = reshape %33 : tile<32xi32> -> tile<32x1xi32>
    %35 = broadcast %34 : tile<32x1xi32> -> tile<32x32xi32>
    %36 = constant <i32: 32> : tile<32x32xi32>
    %37 = muli %35, %36 : tile<32x32xi32>
    %38 = addi %32, %37 : tile<32x32xi32>
    %39 = iota : tile<32xi32>
    %40 = reshape %39 : tile<32xi32> -> tile<1x32xi32>
    %41 = broadcast %40 : tile<1x32xi32> -> tile<32x32xi32>
    %42 = addi %38, %41 : tile<32x32xi32>
    %43 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %44 = broadcast %43 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %45 = offset %44, %42 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %46, %47 = load_ptr_tko weak %45 token=%23 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
    %48 = constant <i32: 0> : tile<i32>
    %49 = reshape %48 : tile<i32> -> tile<1x1xi32>
    %50 = broadcast %49 : tile<1x1xi32> -> tile<32x32xi32>
    %51 = iota : tile<32xi32>
    %52 = reshape %51 : tile<32xi32> -> tile<32x1xi32>
    %53 = broadcast %52 : tile<32x1xi32> -> tile<32x32xi32>
    %54 = constant <i32: 32> : tile<32x32xi32>
    %55 = muli %53, %54 : tile<32x32xi32>
    %56 = addi %50, %55 : tile<32x32xi32>
    %57 = iota : tile<32xi32>
    %58 = reshape %57 : tile<32xi32> -> tile<1x32xi32>
    %59 = broadcast %58 : tile<1x32xi32> -> tile<32x32xi32>
    %60 = constant <i32: 0> : tile<32x32xi32>
    %61 = muli %59, %60 : tile<32x32xi32>
    %62 = addi %56, %61 : tile<32x32xi32>
    %63 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %64 = broadcast %63 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %65 = offset %64, %62 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %66, %67 = load_ptr_tko weak %65 token=%47 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
    %68 = mmaf %29, %46, %4 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
    %69 = mmaf %29, %66, %4 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
    %70 = constant <i32: 1024> : tile<i32>
    %71 = muli %1, %70 : tile<i32>
    %72 = divf %68, %69 rounding<nearest_even> : tile<32x32xf64>
    %73 = reshape %71 : tile<i32> -> tile<1x1xi32>
    %74 = broadcast %73 : tile<1x1xi32> -> tile<32x32xi32>
    %75 = iota : tile<32xi32>
    %76 = reshape %75 : tile<32xi32> -> tile<32x1xi32>
    %77 = broadcast %76 : tile<32x1xi32> -> tile<32x32xi32>
    %78 = constant <i32: 32> : tile<32x32xi32>
    %79 = muli %77, %78 : tile<32x32xi32>
    %80 = addi %74, %79 : tile<32x32xi32>
    %81 = iota : tile<32xi32>
    %82 = reshape %81 : tile<32xi32> -> tile<1x32xi32>
    %83 = broadcast %82 : tile<1x32xi32> -> tile<32x32xi32>
    %84 = addi %80, %83 : tile<32x32xi32>
    %85 = reshape %arg3 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %86 = broadcast %85 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %87 = offset %86, %84 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %88 = store_ptr_tko weak %87, %72 token=%67 : tile<32x32xptr<f64>>, tile<32x32xf64> -> token
    return
  }
}
