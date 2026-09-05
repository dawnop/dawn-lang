cuda_tile.module @m {
  entry @dtype_i64(%arg0: tile<ptr<i64>>, %arg1: tile<ptr<i64>>, %arg2: tile<ptr<i64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<128xi32>
    %8 = iota : tile<128xi32>
    %9 = addi %7, %8 : tile<128xi32>
    %10 = reshape %arg0 : tile<ptr<i64>> -> tile<1xptr<i64>>
    %11 = broadcast %10 : tile<1xptr<i64>> -> tile<128xptr<i64>>
    %12 = offset %11, %9 : tile<128xptr<i64>>, tile<128xi32> -> tile<128xptr<i64>>
    %13, %14 = load_ptr_tko weak %12 token=%0 : tile<128xptr<i64>> -> tile<128xi64>, token
    %15 = reshape %arg1 : tile<ptr<i64>> -> tile<1xptr<i64>>
    %16 = broadcast %15 : tile<1xptr<i64>> -> tile<128xptr<i64>>
    %17 = offset %16, %9 : tile<128xptr<i64>>, tile<128xi32> -> tile<128xptr<i64>>
    %18, %19 = load_ptr_tko weak %17 token=%14 : tile<128xptr<i64>> -> tile<128xi64>, token
    %20 = constant <i32: 0> : tile<i32>
    %21 = addi %5, %20 : tile<i32>
    %22 = addi %13, %18 : tile<128xi64>
    %23 = reshape %21 : tile<i32> -> tile<1xi32>
    %24 = broadcast %23 : tile<1xi32> -> tile<128xi32>
    %25 = iota : tile<128xi32>
    %26 = addi %24, %25 : tile<128xi32>
    %27 = reshape %arg2 : tile<ptr<i64>> -> tile<1xptr<i64>>
    %28 = broadcast %27 : tile<1xptr<i64>> -> tile<128xptr<i64>>
    %29 = offset %28, %26 : tile<128xptr<i64>>, tile<128xi32> -> tile<128xptr<i64>>
    %30 = store_ptr_tko weak %29, %22 token=%19 : tile<128xptr<i64>>, tile<128xi64> -> token
    %31 = constant <i32: 512> : tile<i32>
    %32 = addi %5, %31 : tile<i32>
    %33 = subi %13, %18 : tile<128xi64>
    %34 = reshape %32 : tile<i32> -> tile<1xi32>
    %35 = broadcast %34 : tile<1xi32> -> tile<128xi32>
    %36 = iota : tile<128xi32>
    %37 = addi %35, %36 : tile<128xi32>
    %38 = reshape %arg2 : tile<ptr<i64>> -> tile<1xptr<i64>>
    %39 = broadcast %38 : tile<1xptr<i64>> -> tile<128xptr<i64>>
    %40 = offset %39, %37 : tile<128xptr<i64>>, tile<128xi32> -> tile<128xptr<i64>>
    %41 = store_ptr_tko weak %40, %33 token=%30 : tile<128xptr<i64>>, tile<128xi64> -> token
    %42 = constant <i32: 1024> : tile<i32>
    %43 = addi %5, %42 : tile<i32>
    %44 = muli %13, %18 : tile<128xi64>
    %45 = reshape %43 : tile<i32> -> tile<1xi32>
    %46 = broadcast %45 : tile<1xi32> -> tile<128xi32>
    %47 = iota : tile<128xi32>
    %48 = addi %46, %47 : tile<128xi32>
    %49 = reshape %arg2 : tile<ptr<i64>> -> tile<1xptr<i64>>
    %50 = broadcast %49 : tile<1xptr<i64>> -> tile<128xptr<i64>>
    %51 = offset %50, %48 : tile<128xptr<i64>>, tile<128xi32> -> tile<128xptr<i64>>
    %52 = store_ptr_tko weak %51, %44 token=%41 : tile<128xptr<i64>>, tile<128xi64> -> token
    %53 = constant <i32: 1536> : tile<i32>
    %54 = addi %5, %53 : tile<i32>
    %55 = constant <i64: 4294967296> : tile<128xi64>
    %56 = addi %13, %55 : tile<128xi64>
    %57 = reshape %54 : tile<i32> -> tile<1xi32>
    %58 = broadcast %57 : tile<1xi32> -> tile<128xi32>
    %59 = iota : tile<128xi32>
    %60 = addi %58, %59 : tile<128xi32>
    %61 = reshape %arg2 : tile<ptr<i64>> -> tile<1xptr<i64>>
    %62 = broadcast %61 : tile<1xptr<i64>> -> tile<128xptr<i64>>
    %63 = offset %62, %60 : tile<128xptr<i64>>, tile<128xi32> -> tile<128xptr<i64>>
    %64 = store_ptr_tko weak %63, %56 token=%52 : tile<128xptr<i64>>, tile<128xi64> -> token
    %65 = constant <i32: 2048> : tile<i32>
    %66 = addi %5, %65 : tile<i32>
    %67 = itof %13 signed rounding<nearest_even> : tile<128xi64> -> tile<128xf64>
    %68 = ftoi %67 signed rounding<nearest_int_to_zero> : tile<128xf64> -> tile<128xi64>
    %69 = reshape %66 : tile<i32> -> tile<1xi32>
    %70 = broadcast %69 : tile<1xi32> -> tile<128xi32>
    %71 = iota : tile<128xi32>
    %72 = addi %70, %71 : tile<128xi32>
    %73 = reshape %arg2 : tile<ptr<i64>> -> tile<1xptr<i64>>
    %74 = broadcast %73 : tile<1xptr<i64>> -> tile<128xptr<i64>>
    %75 = offset %74, %72 : tile<128xptr<i64>>, tile<128xi32> -> tile<128xptr<i64>>
    %76 = store_ptr_tko weak %75, %68 token=%64 : tile<128xptr<i64>>, tile<128xi64> -> token
    return
  }
}
